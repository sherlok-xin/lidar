"""Single-frame OPDF prototype integration, with explicit abstention states."""
from __future__ import annotations

import hashlib
import json
import time
import numpy as np

INVALID, E, A, U, G = 0, 1, 2, 3, 4
LABEL_NAMES = {0: 'INVALID', 1: 'E', 2: 'A', 3: 'U', 4: 'G'}
ABLATIONS = ('ground', 'ground_optical', 'ground_geometry', 'full')


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def config_hash(config):
    return hashlib.sha256(json.dumps(json_safe(config), sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def disabled_evidence(frame, kind):
    n = len(frame.xyz)
    if kind == 'optical':
        arrays = {'range_m': np.linalg.norm(frame.xyz, axis=1),
                  'relative_intensity_z': np.full(n, np.nan, np.float32),
                  'optical_weak_score': np.zeros(n, np.float32),
                  'optical_available': np.zeros(n, bool)}
    else:
        arrays = {k: np.zeros(n, np.float32) for k in (
            'scan_surface_score', 'scan_discontinuity_score',
            'spatial_surface_score', 'spatial_diffuse_score')}
        arrays.update({k: np.zeros(n, bool) for k in (
            'scan_available', 'spatial_available', 'edge_protect_mask')})
    arrays['reason_code'] = np.zeros(n, np.uint32)
    return {'arrays': arrays, 'diagnostics': {'status': 'UNAVAILABLE_ABLATION',
                                            'reason': f'{kind}_disabled'}}


def abstain_result(frame, config, reason, *, status='ABSTAIN', error=None):
    valid = np.asarray(frame.valid_xyz_mask, dtype=bool)
    n = len(valid)
    labels = np.where(valid, U, INVALID).astype(np.uint8)
    arrays = {'xyz': frame.xyz, 'intensity': frame.intensity,
              'valid_xyz_mask': valid, 'raw_slot_id': frame.raw_slot_id,
              'labels': labels, 'score_e': np.full(n, np.nan, np.float32),
              'score_a': np.full(n, np.nan, np.float32),
              'available_e': np.zeros(n, bool), 'available_a': np.zeros(n, bool),
              'reason_code': np.zeros(n, np.uint32),
              'retain_solid_mask': valid.copy(), 'retain_with_ground_mask': valid.copy(),
              'aerosol_candidate_mask': np.zeros(n, bool)}
    return {'arrays': arrays,
            'diagnostics': {'status': status, 'quality_alerts': [reason], 'error': error,
                            'm4': {'available': False, 'reason': 'NO_VERIFIED_TEMPORAL_CORRESPONDENCE'},
                            'config_sha256': config_hash(config), 'timings_ms': {}},
            'metadata': frame.metadata()}


def process_frame(frame, config, *, ablation='full'):
    """Return slot-aligned heuristic evidence; never interprets absence as free."""
    if ablation not in ABLATIONS:
        raise ValueError(f'Unknown ablation: {ablation}')
    n = len(frame.xyz)
    if n != frame.height * frame.width:
        return abstain_result(frame, config, 'INCONSISTENT_SHAPE', status='REJECT')
    if n == 0 or not np.any(frame.valid_xyz_mask):
        return abstain_result(frame, config, 'EMPTY_OR_ALL_INVALID_INPUT')
    if frame.height != 80 or len(frame.phase_order) != frame.height or not frame.metadata().get('mapping_available', False):
        return abstain_result(frame, config, 'UNVERIFIED_MAPPING_HEIGHT')
    from . import ground_lite, optical, geometry, decision
    timings = {}
    t0 = time.perf_counter()
    try:
        t = time.perf_counter(); ground = ground_lite.compute(frame, config)
        timings['ground'] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        opt = optical.compute(frame, config) if ablation in ('ground_optical', 'full') else disabled_evidence(frame, 'optical')
        timings['optical'] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        geom = geometry.compute(frame, config) if ablation in ('ground_geometry', 'full') else disabled_evidence(frame, 'geometry')
        timings['geometry'] = (time.perf_counter() - t) * 1000
        t = time.perf_counter(); result = decision.classify(frame, ground, opt, geom, config)
        timings['decision'] = (time.perf_counter() - t) * 1000
        out = dict(result['arrays'])
        labels = np.asarray(out['labels'], dtype=np.uint8)
        if labels.shape != (n,) or not np.isin(labels, list(LABEL_NAMES)).all():
            raise ValueError('Invalid labels shape/enum')
        valid = np.asarray(frame.valid_xyz_mask, dtype=bool)
        if np.any(labels[~valid] != INVALID) or np.any(labels[valid] == INVALID):
            raise ValueError('INVALID and finite XYZ contract violated')
        # Missing evidence must never be transformed into a positive aerosol action.
        if np.any((labels == A) & ~np.asarray(out['available_a'], dtype=bool)):
            raise ValueError('Aerosol assigned without available evidence')
        out.update({'xyz': frame.xyz, 'intensity': frame.intensity,
                    'valid_xyz_mask': valid, 'raw_slot_id': frame.raw_slot_id,
                    'labels': labels, 'retain_solid_mask': (labels == E) | (labels == U),
                    'retain_with_ground_mask': (labels == E) | (labels == U) | (labels == G),
                    'aerosol_candidate_mask': labels == A})
        for prefix, evidence in [('ground', ground), ('optical', opt), ('geometry', geom)]:
            for key, value in evidence['arrays'].items():
                a = np.asarray(value)
                if a.ndim == 0 or a.shape[0] != n:
                    raise ValueError(f'Non slot-aligned feature {prefix}.{key}')
                out[f'{prefix}__{key}'] = a
        timings['total_compute'] = (time.perf_counter() - t0) * 1000
        alerts = []
        if config.get('temporal', {}).get('enabled', False):
            alerts.append('M4_REQUESTED_BUT_UNAVAILABLE_SINGLE_FRAME_FALLBACK')
        return {'arrays': out, 'metadata': frame.metadata(),
                'diagnostics': json_safe({'status': 'OK', 'ablation': ablation,
                    'config_sha256': config_hash(config), 'heuristic_scores_not_probabilities': True,
                    'quality_alerts': alerts, 'timings_ms': timings,
                    'modules': {'ground': ground['diagnostics'], 'optical': opt['diagnostics'],
                                'geometry': geom['diagnostics'], 'decision': result['diagnostics']},
                    'm4': {'available': False, 'reason': 'NO_VERIFIED_TEMPORAL_CORRESPONDENCE',
                           'fallback': 'V1-B', 'synthetic_points_generated': False}})}
    except Exception as exc:
        result = abstain_result(frame, config, 'MODULE_ERROR_RETAIN_UNKNOWN', status='ERROR',
                                error=f'{type(exc).__name__}: {exc}')
        result['diagnostics']['timings_ms']['total_compute'] = (time.perf_counter() - t0) * 1000
        return result
