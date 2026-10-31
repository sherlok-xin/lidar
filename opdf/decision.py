"""M5: conservative evidence conjunction; E/U retained, A is only a candidate."""
from __future__ import annotations

import numpy as np

INVALID, E, A, U, G = 0, 1, 2, 3, 4
DEFAULT_CONFIG = {'entity_scan_surface_min': 0.65, 'entity_spatial_surface_min': 0.60,
                  'aerosol_optical_min': 0.55, 'aerosol_scan_discontinuity_min': 0.65,
                  'aerosol_spatial_diffuse_min': 0.45,
                  'require_reliable_ground_for_aerosol': True}
REASON_BITS = {'INVALID_XYZ': 1, 'GROUND_ACCEPTED': 2, 'LOW_OBJECT_PROTECTED': 4,
               'EDGE_OR_LINE_PROTECTED': 8, 'OPTICAL_WEAK': 16, 'SCAN_DISCONTINUOUS': 32,
               'SPATIAL_DIFFUSE': 64, 'SOLID_AGREEMENT': 128, 'OPTICAL_UNAVAILABLE': 256,
               'SCAN_UNAVAILABLE': 512, 'SPATIAL_UNAVAILABLE': 1024, 'GROUND_UNRELIABLE': 2048,
               'MATERIAL_CONFLICT': 4096, 'INSUFFICIENT_AGREEMENT': 8192,
               'NEAR_GROUND_PROTECTED': 16384, 'AEROSOL_MULTI_EVIDENCE': 32768}


def classify(frame, ground, optical, geometry, config):
    cfg = {**DEFAULT_CONFIG, **config.get('decision', {})}
    n = len(frame.xyz)
    valid = np.asarray(frame.valid_xyz_mask, bool) & np.isfinite(frame.xyz).all(axis=1)
    ga, oa, xa = ground.get('arrays', {}), optical.get('arrays', {}), geometry.get('arrays', {})
    def get(source, name, dtype=float):
        value = source.get(name)
        if value is None:
            return np.zeros(n, bool) if dtype is bool else np.full(n, np.nan)
        return np.asarray(value, dtype=dtype)
    gav = get(ga, 'ground_available', bool) & valid
    ground_mask = get(ga, 'ground_mask', bool) & gav
    low = get(ga, 'low_object_mask', bool) & valid
    near = get(ga, 'near_ground_mask', bool) & valid & ~ground_mask
    edge = get(xa, 'edge_protect_mask', bool) & valid
    ov = get(oa, 'optical_available', bool) & valid
    sv = get(xa, 'scan_available', bool) & valid
    pv = get(xa, 'spatial_available', bool) & valid
    weak = get(oa, 'optical_weak_score')
    surface, discontinuity = get(xa, 'scan_surface_score'), get(xa, 'scan_discontinuity_score')
    solid, diffuse = get(xa, 'spatial_surface_score'), get(xa, 'spatial_diffuse_score')
    ov &= np.isfinite(weak)
    sv &= np.isfinite(surface) & np.isfinite(discontinuity)
    pv &= np.isfinite(solid) & np.isfinite(diffuse)
    available_e = sv & pv
    available_a = ov & sv & pv
    if cfg['require_reliable_ground_for_aerosol']:
        available_a &= gav
    score_e = np.full(n, np.nan, np.float32)
    score_a = np.full(n, np.nan, np.float32)
    score_e[available_e] = np.sqrt(np.clip(surface[available_e] * solid[available_e], 0, 1))
    score_a[available_a] = np.cbrt(np.clip(weak[available_a] * discontinuity[available_a] * diffuse[available_a], 0, 1))
    opt_evidence = ov & (weak >= cfg['aerosol_optical_min'])
    scan_evidence = sv & (discontinuity >= cfg['aerosol_scan_discontinuity_min'])
    spatial_evidence = pv & (diffuse >= cfg['aerosol_spatial_diffuse_min'])
    solid_evidence = available_e & (surface >= cfg['entity_scan_surface_min']) & (solid >= cfg['entity_spatial_surface_min'])
    protect = low | near | edge
    aerosol = available_a & opt_evidence & scan_evidence & spatial_evidence & ~protect & ~solid_evidence & ~ground_mask
    entity = solid_evidence & ~low & ~near & ~ground_mask
    labels = np.where(valid, U, INVALID).astype(np.uint8)
    labels[ground_mask] = G
    labels[entity] = E
    labels[aerosol] = A
    reason = np.zeros(n, np.uint32)
    reason[~valid] |= REASON_BITS['INVALID_XYZ']
    flags = [('GROUND_ACCEPTED', ground_mask), ('LOW_OBJECT_PROTECTED', low),
             ('NEAR_GROUND_PROTECTED', near), ('EDGE_OR_LINE_PROTECTED', edge),
             ('OPTICAL_WEAK', opt_evidence), ('SCAN_DISCONTINUOUS', scan_evidence),
             ('SPATIAL_DIFFUSE', spatial_evidence), ('SOLID_AGREEMENT', solid_evidence),
             ('OPTICAL_UNAVAILABLE', valid & ~ov), ('SCAN_UNAVAILABLE', valid & ~sv),
             ('SPATIAL_UNAVAILABLE', valid & ~pv), ('GROUND_UNRELIABLE', valid & ~gav),
             ('MATERIAL_CONFLICT', valid & opt_evidence & (solid_evidence | protect)),
             ('INSUFFICIENT_AGREEMENT', valid & (labels == U)), ('AEROSOL_MULTI_EVIDENCE', aerosol)]
    for name, mask in flags:
        reason[mask] |= REASON_BITS[name]
    return {'arrays': {'labels': labels, 'score_e': score_e, 'score_a': score_a,
                       'available_e': available_e, 'available_a': available_a, 'reason_code': reason},
            'diagnostics': {'module': 'decision', 'status': 'OK', 'reason_bits': REASON_BITS,
                            'labels': {'INVALID': INVALID, 'E': E, 'A': A, 'U': U, 'G': G},
                            'semantics': 'heuristic scores, not posteriors; A is aerosol candidate, U is retained unknown',
                            'counts': {name: int((labels == value).sum()) for name, value in [('INVALID', INVALID), ('E', E), ('A', A), ('U', U), ('G', G)]}}}
