"""M3: scan adjacency plus batched adaptive-radius 3-D support/PCA."""
from __future__ import annotations

import warnings
import numpy as np
from scipy.spatial import cKDTree

DEFAULT_CONFIG = {
    'phase_order_trusted': True, 'min_phase_samples': 10,
    'max_adjacent_phase_gap_deg': 4.0, 'max_phase_mad_deg': 0.15,
    'max_column_gap_deg': 0.80, 'scan_column_radius': 2,
    'scan_min_neighbors': 4, 'surface_depth_m': 0.18, 'surface_depth_ratio': 0.012,
    'far_gap_m': 1.0, 'min_search_radius_m': 0.18, 'radius_scale': 0.014,
    'max_search_radius_m': 0.90, 'knn': 16, 'pca_min_neighbors': 5,
    'batch_size': 4096, 'workers': 2, 'min_eigenvalue_extent_m2': 1e-7,
    'line_protect_threshold': 0.65, 'edge_min_surface_score': 0.15,
    'edge_min_discontinuity_score': 0.35,
}
REASON_BITS = {'INVALID_XYZ': 1, 'SCAN_UNAVAILABLE': 2, 'SPATIAL_UNAVAILABLE': 4,
               'EDGE_OR_LINE_PROTECT': 8, 'PCA_DEGENERATE': 16, 'PHASE_UNTRUSTED': 32}


def _shift(a, dr, dc):
    out = np.full(a.shape, np.nan, np.float64)
    h, w = a.shape
    if abs(dr) >= h or abs(dc) >= w:
        return out
    out[max(0, dr):min(h, h + dr), max(0, dc):min(w, w + dc)] = a[
        max(0, -dr):min(h, h - dr), max(0, -dc):min(w, w - dc)]
    return out


def compute(frame, config):
    cfg = {**DEFAULT_CONFIG, **config.get('geometry', {})}
    xyz = np.asarray(frame.xyz, np.float64)
    valid = np.asarray(frame.valid_xyz_mask, bool) & np.isfinite(xyz).all(axis=1)
    n = len(xyz)
    arrays = {key: np.full(n, np.nan, np.float32) for key in (
        'scan_surface_score', 'scan_discontinuity_score', 'scan_far_ratio',
        'spatial_surface_score', 'spatial_diffuse_score', 'density_per_m3', 'linearity', 'planarity')}
    arrays.update(pca_eigenvalues=np.full((n, 3), np.nan, np.float32),
                  spatial_neighbor_count=np.zeros(n, np.int16),
                  scan_valid_neighbor_count=np.zeros(n, np.int16),
                  effective_phase_support=np.zeros(n, np.int16),
                  scan_range_jump_m=np.full(n, np.nan, np.float32),
                  search_radius_m=np.full(n, np.nan, np.float32))
    arrays.update(scan_available=np.zeros(n, bool), spatial_available=np.zeros(n, bool),
                  edge_protect_mask=np.zeros(n, bool),
                  reason_code=np.where(valid, 2 | 4, 1).astype(np.uint32))
    diag = {'module': 'geometry', 'status': 'UNAVAILABLE', 'reason_bits': REASON_BITS,
            'semantics': 'local shape/angular scores; not sufficient aerosol evidence',
            'angular_seam_wrapped': False, 'spatial_neighbor_cap': int(cfg['knn']) - 1}
    result = {'arrays': arrays, 'diagnostics': diag}
    if not valid.any() or frame.height * frame.width != n or frame.width < 2:
        return result
    rrflat = np.linalg.norm(xyz, axis=1)
    azflat = np.arctan2(xyz[:, 1], xyz[:, 0])
    elflat = np.degrees(np.arctan2(xyz[:, 2], np.hypot(xyz[:, 0], xyz[:, 1])))
    rr = frame.to_image(np.where(valid, rrflat, np.nan))
    az = frame.to_image(np.where(valid, azflat, np.nan))
    el = frame.to_image(np.where(valid, elflat, np.nan))
    coverage = np.asarray(frame.column_coverage_mask, bool)
    if coverage.shape != (frame.width,):
        return result
    rr[:, ~coverage] = np.nan
    az[:, ~coverage] = np.nan
    el[:, ~coverage] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        phase_el = np.nanmedian(el, axis=1)
        phase_mad = np.nanmedian(np.abs(el - phase_el[:, None]), axis=1)
    phase_supported = (np.isfinite(el).sum(axis=1) >= cfg['min_phase_samples']) & (phase_mad <= cfg['max_phase_mad_deg'])
    phase_gap = np.diff(phase_el)
    adjacent_ok = (phase_supported[1:] & phase_supported[:-1] & (phase_gap > 0) &
                   (phase_gap <= cfg['max_adjacent_phase_gap_deg']) & bool(cfg['phase_order_trusted']))
    scan_count = np.zeros(rr.shape, np.int16)
    coherent_count = np.zeros(rr.shape, np.int16)
    far_count = np.zeros(rr.shape, np.int16)
    phase_count = np.zeros(rr.shape, np.int16)
    jump_sum = np.zeros(rr.shape, np.float64)
    offsets = [(0, dc) for dc in range(-int(cfg['scan_column_radius']), int(cfg['scan_column_radius']) + 1) if dc]
    offsets += [(-1, 0), (1, 0)]
    for dr, dc in offsets:
        other_r = _shift(rr, dr, dc)
        other_az = _shift(az, dr, dc)
        delta_az = np.abs(np.degrees(np.arctan2(np.sin(other_az - az), np.cos(other_az - az))))
        usable = np.isfinite(rr) & np.isfinite(other_r) & (delta_az <= cfg['max_column_gap_deg'])
        if dr:
            row_ok = np.zeros(frame.height, bool)
            if dr > 0:
                row_ok[1:] = adjacent_ok
            else:
                row_ok[:-1] = adjacent_ok
            usable &= row_ok[:, None]
        scan_count += usable
        if dr:
            phase_count += usable
        jump_sum += np.where(usable, np.abs(other_r - rr), 0.0)
        coherent_count += usable & (np.abs(other_r - rr) <= np.maximum(cfg['surface_depth_m'], cfg['surface_depth_ratio'] * rr))
        far_count += usable & (other_r - rr >= cfg['far_gap_m'])
    available_image = (scan_count >= cfg['scan_min_neighbors']) & np.isfinite(rr)
    scan_available = frame.from_image(available_image) & valid
    surface = frame.from_image(coherent_count / np.maximum(scan_count, 1))
    far = frame.from_image(far_count / np.maximum(scan_count, 1))
    arrays['scan_available'] = scan_available
    arrays['scan_valid_neighbor_count'] = frame.from_image(scan_count).astype(np.int16)
    arrays['effective_phase_support'] = frame.from_image(phase_count).astype(np.int16)
    jump_flat = frame.from_image(jump_sum / np.maximum(scan_count, 1))
    arrays['scan_range_jump_m'][scan_available] = jump_flat[scan_available]
    arrays['scan_surface_score'][scan_available] = surface[scan_available]
    arrays['scan_discontinuity_score'][scan_available] = 1.0 - surface[scan_available]
    arrays['scan_far_ratio'][scan_available] = far[scan_available]
    arrays['reason_code'][scan_available] &= np.uint32(~REASON_BITS['SCAN_UNAVAILABLE'] & 0xffffffff)
    if not adjacent_ok.any():
        arrays['reason_code'][valid] |= REASON_BITS['PHASE_UNTRUSTED']
    vi = np.flatnonzero(valid)
    points = xyz[vi]
    if len(points) >= cfg['pca_min_neighbors'] + 1:
        tree = cKDTree(points)
        k = min(int(cfg['knn']), len(points))
        batch = max(1, int(cfg['batch_size']))
        for start in range(0, len(points), batch):
            end = min(start + batch, len(points))
            q = points[start:end]
            radii = np.clip(cfg['radius_scale'] * rrflat[vi[start:end]],
                            cfg['min_search_radius_m'], cfg['max_search_radius_m'])
            distance, indices = tree.query(q, k=k, distance_upper_bound=cfg['max_search_radius_m'], workers=int(cfg['workers']))
            if k == 1:
                distance, indices = distance[:, None], indices[:, None]
            # A point cannot support itself. Duplicate points are retained as observations,
            # but zero-extent covariance is explicitly unavailable below.
            support = (indices < len(points)) & (distance <= radii[:, None])
            support &= indices != np.arange(start, end)[:, None]
            count = support.sum(axis=1)
            neighbor = points[np.minimum(indices, len(points) - 1)] - q[:, None, :]
            weight = support.astype(np.float64)
            mean = np.einsum('bk,bki->bi', weight, neighbor) / np.maximum(count, 1)[:, None]
            centered = neighbor - mean[:, None, :]
            covariance = np.einsum('bk,bki,bkj->bij', weight, centered, centered) / np.maximum(count, 1)[:, None, None]
            eig = np.maximum(np.linalg.eigvalsh(covariance), 0)
            available = (count >= cfg['pca_min_neighbors']) & (eig[:, 2] > cfg['min_eigenvalue_extent_m2'])
            linearity = (eig[:, 2] - eig[:, 1]) / np.maximum(eig[:, 2], 1e-15)
            planarity = (eig[:, 1] - eig[:, 0]) / np.maximum(eig[:, 2], 1e-15)
            diffuse = 3.0 * eig[:, 0] / np.maximum(eig.sum(axis=1), 1e-15)
            ids = vi[start:end]
            aa = ids[available]
            arrays['spatial_neighbor_count'][ids] = count.astype(np.int16)
            arrays['search_radius_m'][ids] = radii.astype(np.float32)
            arrays['spatial_available'][aa] = True
            arrays['spatial_surface_score'][aa] = np.maximum(linearity, planarity)[available]
            arrays['spatial_diffuse_score'][aa] = np.clip(diffuse[available], 0, 1)
            arrays['linearity'][aa] = linearity[available]
            arrays['planarity'][aa] = planarity[available]
            arrays['pca_eigenvalues'][aa] = eig[available].astype(np.float32)
            arrays['density_per_m3'][aa] = count[available] / ((4.0 / 3.0) * np.pi * radii[available] ** 3)
            arrays['reason_code'][aa] &= np.uint32(~REASON_BITS['SPATIAL_UNAVAILABLE'] & 0xffffffff)
            arrays['reason_code'][ids[(count >= cfg['pca_min_neighbors']) & ~available]] |= REASON_BITS['PCA_DEGENERATE']
    protect = (scan_available & (arrays['scan_surface_score'] >= cfg['edge_min_surface_score']) &
               (arrays['scan_discontinuity_score'] >= cfg['edge_min_discontinuity_score']))
    protect |= arrays['spatial_available'] & (arrays['linearity'] >= cfg['line_protect_threshold'])
    arrays['edge_protect_mask'] = protect & valid
    arrays['reason_code'][protect] |= REASON_BITS['EDGE_OR_LINE_PROTECT']
    diag.update(status='OK', scan_available_points=int(scan_available.sum()),
                spatial_available_points=int(arrays['spatial_available'].sum()),
                trusted_adjacent_phase_pairs=int(adjacent_ok.sum()),
                edge_or_line_protected=int(protect.sum()), capped_density=True)
    return result
