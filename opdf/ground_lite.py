"""M1: conservative, auditable single-plane proposal; no learned ground truth."""
from __future__ import annotations

import numpy as np

DEFAULT_CONFIG = {
    'seed': 712, 'cell_size_m': 1.0, 'lower_quantile': 0.15,
    'min_cell_points': 3, 'seed_z_min_m': -4.0, 'seed_z_max_m': -0.30,
    'min_range_m': 1.0, 'max_fit_range_m': 45.0, 'min_candidates': 24,
    'min_quadrants': 3, 'min_radial_span_m': 6.0, 'max_fit_points': 4000,
    'ransac_trials': 72, 'inlier_residual_m': 0.12, 'min_inlier_ratio': 0.55,
    'max_slope': 0.35, 'max_median_residual_m': 0.08,
    'max_near_far_median_residual_m': 0.10, 'ground_below_m': 0.10,
    'ground_above_m': 0.035, 'low_object_height_m': 0.40,
    'near_ground_height_m': 0.45, 'support_range_margin_m': 2.0,
}
REASON_BITS = {'INVALID_XYZ': 1, 'PLANE_UNRELIABLE': 2, 'GROUND_BAND': 4,
               'LOW_OBJECT_PROTECT': 8, 'OUTSIDE_PLANE_SUPPORT': 16}


def compute(frame, config):
    cfg = {**DEFAULT_CONFIG, **config.get('ground', {})}
    xyz = np.asarray(frame.xyz, dtype=np.float64)
    valid = np.asarray(frame.valid_xyz_mask, bool) & np.isfinite(xyz).all(axis=1)
    n = len(xyz)
    arrays = {'ground_height': np.full(n, np.nan, np.float32),
              'height_above_ground': np.full(n, np.nan, np.float32),
              'plane_residual_m': np.full(n, np.nan, np.float32),
              'ground_available': np.zeros(n, bool), 'ground_mask': np.zeros(n, bool),
              'low_object_mask': np.zeros(n, bool), 'near_ground_mask': np.zeros(n, bool),
              'reason_code': np.where(valid, 2, 1).astype(np.uint32)}
    diag = {'module': 'ground_lite', 'status': 'UNAVAILABLE', 'reliable': False,
            'reason_bits': REASON_BITS, 'candidate_count': 0,
            'semantics': 'heuristic single-plane support; not terrain truth'}
    result = {'arrays': arrays, 'diagnostics': diag}
    if not valid.any():
        diag['rejection'] = 'NO_FINITE_POINTS'
        return result
    ranges = np.hypot(xyz[:, 0], xyz[:, 1])
    idx = np.flatnonzero(valid & (ranges >= cfg['min_range_m']) &
                         (ranges <= cfg['max_fit_range_m']) &
                         (xyz[:, 2] >= cfg['seed_z_min_m']) &
                         (xyz[:, 2] <= cfg['seed_z_max_m']))
    if not len(idx):
        diag['rejection'] = 'NO_LOWER_SEEDS'
        return result
    cells = np.floor(xyz[idx, :2] / cfg['cell_size_m']).astype(np.int64)
    _, inverse = np.unique(cells, axis=0, return_inverse=True)
    order = np.argsort(inverse, kind='stable')
    groups = np.split(order, np.flatnonzero(np.diff(inverse[order])) + 1)
    candidates = []
    for group in groups:
        if len(group) < cfg['min_cell_points']:
            continue
        points = xyz[idx[group]]
        z = np.quantile(points[:, 2], cfg['lower_quantile'])
        candidates.append(points[np.argmin(np.abs(points[:, 2] - z))])
    points = np.asarray(candidates, dtype=np.float64).reshape(-1, 3)
    diag['candidate_count'] = len(points)
    if len(points) < cfg['min_candidates']:
        diag['rejection'] = 'INSUFFICIENT_PARTITION_COVERAGE'
        return result
    rng = np.random.default_rng(int(cfg['seed']))
    if len(points) > cfg['max_fit_points']:
        points = points[np.sort(rng.choice(len(points), cfg['max_fit_points'], replace=False))]
    design = np.column_stack((points[:, :2], np.ones(len(points))))
    z = points[:, 2]
    best = None
    best_key = (-1, -np.inf)
    for _ in range(int(cfg['ransac_trials'])):
        sample = rng.choice(len(points), 3, replace=False)
        if np.linalg.matrix_rank(design[sample]) < 3:
            continue
        coef = np.linalg.solve(design[sample], z[sample])
        if np.hypot(*coef[:2]) > cfg['max_slope']:
            continue
        residual = np.abs(z - design @ coef)
        inside = residual <= cfg['inlier_residual_m']
        key = (int(inside.sum()), -float(np.median(residual[inside])) if inside.any() else -np.inf)
        if key > best_key:
            best_key, best = key, inside
    if best is None or best.sum() < cfg['min_candidates']:
        diag['rejection'] = 'NO_NONDEGENERATE_PLANE'
        return result
    for _ in range(3):
        coef = np.linalg.lstsq(design[best], z[best], rcond=None)[0]
        residual = np.abs(z - design @ coef)
        updated = residual <= cfg['inlier_residual_m']
        if updated.sum() < 3:
            break
        best = updated
    supported = points[best]
    rr = np.hypot(supported[:, 0], supported[:, 1])
    quadrants = ((supported[:, 0] >= 0).astype(int) + 2 * (supported[:, 1] >= 0)).astype(int)
    radius_mid = float(np.median(rr))
    supported_residual = np.abs(supported[:, 2] - np.column_stack((supported[:, :2], np.ones(len(supported)))) @ coef)
    near = supported_residual[rr <= radius_mid]
    far = supported_residual[rr > radius_mid]
    slope = float(np.hypot(*coef[:2]))
    checks = {
        'inlier_ratio': float(best.mean()) >= cfg['min_inlier_ratio'],
        'quadrants': len(np.unique(quadrants)) >= cfg['min_quadrants'],
        'radial_span': float(np.ptp(rr)) >= cfg['min_radial_span_m'],
        'slope': slope <= cfg['max_slope'],
        'residual': float(np.median(supported_residual)) <= cfg['max_median_residual_m'],
        'near_residual': bool(len(near)) and float(np.median(near)) <= cfg['max_near_far_median_residual_m'],
        'far_residual': bool(len(far)) and float(np.median(far)) <= cfg['max_near_far_median_residual_m'],
    }
    diag.update({'acceptance_checks': checks, 'plane_z_ax_by_c': coef.tolist(),
                 'plane_up_normal': (np.r_[-coef[:2], 1.] / np.linalg.norm(np.r_[-coef[:2], 1.])).tolist(),
                 'coordinate_assumption': 'raw Z approximately up; single-plane hypothesis, not certified extrinsics',
                 'inlier_ratio': float(best.mean()), 'slope': slope,
                 'inlier_median_absolute_residual_m': float(np.median(supported_residual)),
                 'support_radial_span_m': float(np.ptp(rr))})
    if not all(checks.values()):
        diag['rejection'] = 'PLANE_ACCEPTANCE_FAILED'
        return result
    available = valid & (ranges >= cfg['min_range_m']) & (ranges <= min(cfg['max_fit_range_m'], float(rr.max()) + cfg['support_range_margin_m']))
    height = xyz[:, 2] - (xyz[:, 0] * coef[0] + xyz[:, 1] * coef[1] + coef[2])
    arrays['ground_height'][available] = height[available]
    arrays['height_above_ground'][available] = height[available]
    arrays['plane_residual_m'][available] = np.abs(height[available])
    arrays['ground_available'] = available
    arrays['ground_mask'] = available & (height >= -cfg['ground_below_m']) & (height <= cfg['ground_above_m'])
    arrays['low_object_mask'] = available & (height > cfg['ground_above_m']) & (height <= cfg['low_object_height_m'])
    arrays['near_ground_mask'] = available & (height <= cfg['near_ground_height_m'])
    arrays['reason_code'][available] = 0
    arrays['reason_code'][valid & ~available] = REASON_BITS['OUTSIDE_PLANE_SUPPORT']
    arrays['reason_code'][arrays['ground_mask']] |= REASON_BITS['GROUND_BAND']
    arrays['reason_code'][arrays['low_object_mask']] |= REASON_BITS['LOW_OBJECT_PROTECT']
    diag.update(status='OK', reliable=True, ground_points=int(arrays['ground_mask'].sum()),
                low_object_protected=int(arrays['low_object_mask'].sum()))
    return result
