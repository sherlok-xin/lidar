"""M2: local, range-compatible intensity residual, never physical reflectivity."""
from __future__ import annotations

import warnings
import numpy as np

DEFAULT_CONFIG = {'column_radius': 2, 'phase_radius': 1, 'min_neighbors': 4,
                  'range_tolerance_m': 1.0, 'range_tolerance_ratio': 0.08,
                  'mad_floor': 1.0, 'weak_z_scale': 1.5}
REASON_BITS = {'INVALID_XYZ': 1, 'NO_INTENSITY': 2, 'INSUFFICIENT_LOCAL_SUPPORT': 4,
               'RELATIVE_DIM_RETURN': 8, 'UNSUPPORTED_LAYOUT': 16}


def _shift(image, dr, dc):
    """No angular seam wrap: delivered columns only."""
    out = np.full(image.shape, np.nan, np.float64)
    h, w = image.shape
    if abs(dr) >= h or abs(dc) >= w:
        return out
    rs = slice(max(0, dr), min(h, h + dr))
    cs = slice(max(0, dc), min(w, w + dc))
    out[rs, cs] = image[slice(max(0, -dr), min(h, h - dr)),
                         slice(max(0, -dc), min(w, w - dc))]
    return out


def compute(frame, config):
    cfg = {**DEFAULT_CONFIG, **config.get('optical', {})}
    xyz = np.asarray(frame.xyz, np.float64)
    valid = np.asarray(frame.valid_xyz_mask, bool) & np.isfinite(xyz).all(axis=1)
    intensity = np.asarray(frame.intensity, np.float64)
    n = len(xyz)
    ranges = np.linalg.norm(xyz, axis=1)
    ranges[~valid] = np.nan
    arrays = {'range_m': ranges.astype(np.float32), 'relative_intensity_z': np.full(n, np.nan, np.float32),
              'intensity': intensity.astype(np.float32),
              'local_intensity_median': np.full(n, np.nan, np.float32),
              'local_intensity_mad': np.full(n, np.nan, np.float32),
              'local_intensity_neighbor_count': np.zeros(n, np.int16),
              'optical_weak_score': np.full(n, np.nan, np.float32),
              'optical_available': np.zeros(n, bool),
              'reason_code': np.where(valid, 4, 1).astype(np.uint32)}
    diag = {'module': 'optical', 'status': 'UNAVAILABLE', 'reason_bits': REASON_BITS,
            'semantics': 'local robust intensity score, not reflectivity or posterior'}
    result = {'arrays': arrays, 'diagnostics': diag}
    if n == 0 or frame.height * frame.width != n or frame.width < 2:
        arrays['reason_code'][valid] = REASON_BITS['UNSUPPORTED_LAYOUT']
        return result
    good_i = valid & np.isfinite(intensity)
    arrays['reason_code'][valid & ~good_i] = REASON_BITS['NO_INTENSITY']
    image = frame.to_image(np.where(good_i, intensity, np.nan))
    rr = frame.to_image(ranges)
    coverage = np.asarray(frame.column_coverage_mask, bool)
    if coverage.shape != (frame.width,):
        arrays['reason_code'][valid] |= REASON_BITS['UNSUPPORTED_LAYOUT']
        return result
    image[:, ~coverage] = np.nan
    rr[:, ~coverage] = np.nan
    neighbor_images = []
    tolerance = cfg['range_tolerance_m'] + cfg['range_tolerance_ratio'] * rr
    for dr in range(-int(cfg['phase_radius']), int(cfg['phase_radius']) + 1):
        for dc in range(-int(cfg['column_radius']), int(cfg['column_radius']) + 1):
            if dr == 0 and dc == 0:
                continue
            other_i, other_r = _shift(image, dr, dc), _shift(rr, dr, dc)
            other_i[np.abs(other_r - rr) > tolerance] = np.nan
            other_i[~np.isfinite(other_r) | ~np.isfinite(rr)] = np.nan
            neighbor_images.append(other_i)
    if not neighbor_images:
        return result
    samples = np.stack(neighbor_images)
    count = np.isfinite(samples).sum(axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        median = np.nanmedian(samples, axis=0)
        mad = np.nanmedian(np.abs(samples - median), axis=0)
    z = (image - median) / np.maximum(1.4826 * mad, cfg['mad_floor'])
    available_image = np.isfinite(z) & (count >= cfg['min_neighbors'])
    available = np.asarray(frame.from_image(available_image), bool) & good_i
    zflat = frame.from_image(z)
    arrays['local_intensity_neighbor_count'] = frame.from_image(count).astype(np.int16)
    arrays['local_intensity_median'][available] = frame.from_image(median)[available]
    arrays['local_intensity_mad'][available] = frame.from_image(mad)[available]
    arrays['relative_intensity_z'][available] = zflat[available]
    arrays['optical_weak_score'][available] = np.clip(-zflat[available] / cfg['weak_z_scale'], 0, 1)
    arrays['optical_available'] = available
    arrays['reason_code'][available] = 0
    arrays['reason_code'][available & (zflat < 0)] |= REASON_BITS['RELATIVE_DIM_RETURN']
    diag.update(status='OK' if available.any() else 'UNAVAILABLE', available_points=int(available.sum()))
    return result
