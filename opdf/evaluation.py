"""Behavior diagnostics only. Without independent reference labels: no accuracy."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import numpy as np
from .visualization import load_result


def _metadata(npz_path, metadata=None):
    if metadata is not None:
        return metadata
    sidecar = Path(npz_path).with_suffix('.json')
    return json.loads(sidecar.read_text()) if sidecar.exists() else {}


def frame_metrics(npz_path, metadata=None):
    """Scalar counts/rates with finite-XYZ denominators (U is not discarded)."""
    a = load_result(npz_path)
    m = _metadata(npz_path, metadata)
    finite = np.isfinite(a['xyz']).all(axis=1) & a['valid_xyz_mask'].astype(bool)
    n, nv = len(finite), int(finite.sum())
    labels = a['labels']
    result = dict(frame=Path(npz_path).stem, measurement_type='HEURISTIC_BEHAVIOR_NO_GT',
                  status=str(m.get('status', m.get('diagnostics', {}).get('status', 'UNKNOWN'))),
                  total_slots=n, valid_xyz_count=nv, invalid_xyz_count=n-nv,
                  valid_xyz_fraction=nv/n if n else None,
                  invalid_label_mismatch_count=int(((labels == 0) != ~finite).sum()),
                  no_independent_gt=True)
    for value, name in ((1, 'e'), (2, 'a'), (3, 'u'), (4, 'g')):
        count = int((finite & (labels == value)).sum())
        result[f'{name}_candidate_count'] = count
        result[f'{name}_candidate_rate_of_valid'] = count / nv if nv else None
    result['protected_e_u_count'] = result['e_candidate_count'] + result['u_candidate_count']
    result['protected_e_u_rate_of_valid'] = result['protected_e_u_count']/nv if nv else None
    for name in ('e', 'a'):
        available = a[f'available_{name}'].astype(bool) & finite
        result[f'{name}_score_available_count'] = int(available.sum())
        result[f'{name}_score_unavailable_count'] = int((finite & ~available).sum())
    radius = np.linalg.norm(a['xyz'], axis=1)
    for lo, hi, tag in ((0, 5, '0_5'), (5, 10, '5_10'), (10, 20, '10_20'),
                         (20, 50, '20_50'), (50, np.inf, '50_inf')):
        _band(result, finite & (radius >= lo) & (radius < hi), labels, 'range_'+tag)
    z = a['xyz'][:, 2]
    for lo, hi, tag in ((-np.inf, -1, 'below_minus1'), (-1, 0, 'minus1_0'),
                         (0, 1, '0_1'), (1, 3, '1_3'), (3, np.inf, '3_inf')):
        _band(result, finite & (z >= lo) & (z < hi), labels, 'z_'+tag)
    result['height_band_reference'] = 'RAW_FRAME_Z_NOT_CERTIFIED_HEIGHT_ABOVE_GROUND'
    if 'ground__ground_height' in a:
        hg = a['ground__ground_height']
        hg_valid = finite & np.isfinite(hg) & a.get('ground__ground_available', np.zeros(n, bool))
        result['fitted_ground_height_available_count'] = int(hg_valid.sum())
        result['fitted_ground_height_unavailable_count'] = int((finite & ~hg_valid).sum())
        for lo, hi, tag in ((-np.inf,0,'below0'),(0,.15,'0_015'),(.15,.4,'015_04'),
                            (.4,1.,'04_1'),(1.,2.,'1_2'),(2.,np.inf,'2_inf')):
            _band(result,hg_valid & (hg>=lo) & (hg<hi),labels,'fitted_height_'+tag)
        result['fitted_height_reference'] = 'heuristic accepted single plane; not physical terrain truth'
    # Flatten any genuine module timings; absence means unmeasured, not 0 ms.
    for container_name in ('timings_ms', 'modules_timings_ms', 'timing_ms'):
        container = m.get(container_name, m.get('diagnostics', {}).get(container_name, {}))
        if isinstance(container, dict):
            for k, v in container.items():
                if isinstance(v, (int, float)) and np.isfinite(v):
                    result[f'timing_ms_{k}'] = float(v)
    for k in ('height', 'width', 'header_stamp_ns', 'record_stamp_ns', 'frame_id'):
        value = m.get(k, m.get('metadata', {}).get(k))
        if value is not None:
            result[k] = value
    return result


def _band(result, mask, labels, prefix):
    n = int(mask.sum())
    result[prefix+'_valid_count'] = n
    for value, name in ((1, 'e'), (2, 'a'), (3, 'u'), (4, 'g')):
        count = int((mask & (labels == value)).sum())
        result[prefix+f'_{name}_candidate_count'] = count
        result[prefix+f'_{name}_candidate_rate'] = count/n if n else None


def validate_reference_labels(npz_path, reference_path):
    """Validate a future independent L2 reference import, without scoring it.

    JSON requires source_message_sha256, source_npz_sha256, reviewer_id,
    annotation_version, provenance, independent=true, and per-slot labels.
    U is permitted. This structural validator cannot certify semantic truth.
    """
    import hashlib
    a = load_result(npz_path)
    ref = json.loads(Path(reference_path).read_text())
    for key in ('source_message_sha256', 'source_npz_sha256', 'reviewer_id',
                'annotation_version', 'provenance', 'independent', 'annotations'):
        if key not in ref or ref[key] in ('', None):
            raise ValueError(f'Reference missing {key}')
    if ref['independent'] is not True:
        raise ValueError('Reference must explicitly assert independent annotation')
    if ref['source_npz_sha256'] != hashlib.sha256(Path(npz_path).read_bytes()).hexdigest():
        raise ValueError('Reference NPZ fingerprint mismatch')
    sidecar = _metadata(npz_path)
    source_metadata = sidecar.get('metadata', sidecar)
    expected_message_hash = source_metadata.get('raw_message_sha256')
    if not expected_message_hash:
        expected_message_hash = source_metadata.get('source_fingerprint', {}).get('raw_message_sha256')
    if not expected_message_hash or ref['source_message_sha256'] != expected_message_hash:
        raise ValueError('Reference source message fingerprint mismatch or missing source metadata')
    valid_ids = {int(x) for x in a['raw_slot_id'][np.isfinite(a['xyz']).all(axis=1) & a['valid_xyz_mask'].astype(bool)]}
    seen = set()
    for row in ref['annotations']:
        slot = row.get('raw_slot_id')
        if isinstance(slot, bool) or not isinstance(slot, int) or slot not in valid_ids or slot in seen:
            raise ValueError('Reference contains invalid/duplicate/nonfinite slot')
        if row.get('label') not in ('E', 'A', 'U', 'G'):
            raise ValueError('Reference label must be E/A/U/G')
        seen.add(slot)
    if not seen:
        raise ValueError('Empty annotation is not a usable reference')
    return dict(structure_valid=True, semantic_truth_certified=False,
                annotated_slots=len(seen), unannotated_valid_slots=len(valid_ids-seen),
                performance_computed=False)


def write_run_report(run_dir):
    root = Path(run_dir)
    paths = sorted((root/'frames').glob('*.npz'))
    rows = [frame_metrics(p) for p in paths]
    keys = list(dict.fromkeys(k for row in rows for k in row))
    out = root/'metrics.csv'
    with out.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys or ['frame', 'measurement_type'])
        writer.writeheader(); writer.writerows(rows)
    report = root/'behavior_report.md'
    lines = ['# OPDF-V1 heuristic behavior report', '',
             'Candidate labels and scores are algorithm outputs, not independent truth. '
             'No precision, recall, accuracy, obstacle safety or false-stop performance was computed.', '',
             f'Frames: {len(rows)}. All valid-XYZ denominators include unknown/rejected U points. '
             'Empty bands are NA. Raw Z bins are not certified ground-relative height.', '',
             '| Frame | Status | Valid XYZ | E | A | U | G |', '|---|---|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append('| '+ ' | '.join(str(r[k]) for k in ('frame', 'status', 'valid_xyz_count',
                     'e_candidate_count', 'a_candidate_count', 'u_candidate_count', 'g_candidate_count'))+' |')
    report.write_text('\n'.join(lines)+'\n')
    summary = dict(frames=len(rows), total_slots=sum(r['total_slots'] for r in rows),
                   valid_xyz_count=sum(r['valid_xyz_count'] for r in rows),
                   counts={name: sum(r[f'{name}_candidate_count'] for r in rows) for name in 'eaug'},
                   metrics_csv=str(out), behavior_report=str(report), no_independent_gt=True,
                   performance_computed=False)
    (root/'behavior_summary.json').write_text(json.dumps(summary, indent=2))
    return summary
