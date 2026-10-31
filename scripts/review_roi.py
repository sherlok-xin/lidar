#!/usr/bin/env python3
"""Exact full-NPZ ROI review, blind evidence and reproducible cache regression.

ROI bounds are inclusive; explicit raw slot selection can include invalid slots.
No annotation is invented: reviewer/confidence/human_label default to null.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'.cache/matplotlib'))
import numpy as np
from opdf.visualization import (load_result, select_slots, normalize_view, render_frame,
                                _viewer_html, _json_numbers)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    from opdf.pipeline import json_safe
    Path(path).write_text(json.dumps(json_safe(obj), ensure_ascii=False, indent=2, allow_nan=False))


def exact_selection(arrays, roi):
    """Explicit slot queries include invalid measured slots for diagnosis."""
    spec = roi or {}
    if not isinstance(spec, dict):
        spec = {'bbox': spec}
    requested = spec.get('raw_slot_ids')
    if requested is not None:
        if any(isinstance(i, bool) or not isinstance(i, (int, np.integer)) or i < 0 for i in requested):
            raise ValueError('raw slots must be nonnegative integers')
        absent = set(map(int, requested)) - set(map(int, arrays['raw_slot_id']))
        if absent:
            raise ValueError(f'Requested slots not in this exact frame: {sorted(absent)[:20]}')
        indices = np.flatnonzero(np.isin(arrays['raw_slot_id'], requested))
        if spec.get('bbox') is not None:
            indices = np.intersect1d(indices, select_slots(arrays, {'bbox': spec['bbox']}))
    else:
        indices = select_slots(arrays, spec)
    return indices[np.argsort(arrays['raw_slot_id'][indices], kind='stable')]


def _blind_screenshot(arrays, exact, output, camera, cap):
    # Blind artifact contains actual raw XYZ/intensity only, never pseudo U labels.
    valid = np.isfinite(arrays['xyz'][exact]).all(axis=1) & arrays['valid_xyz_mask'][exact]
    order = exact[valid]
    if len(order) > cap:
        order = order[np.linspace(0, len(order)-1, cap, dtype=np.int64)]
    xyz = arrays['xyz'][order]
    import matplotlib
    matplotlib.use('Agg')
    import mpl_toolkits
    matching = Path(matplotlib.__file__).resolve().parent.parent/'mpl_toolkits'
    if (matching/'mplot3d').is_dir():
        mpl_toolkits.__path__ = [str(matching)] + [str(p) for p in mpl_toolkits.__path__ if str(p) != str(matching)]
    from mpl_toolkits.mplot3d import Axes3D
    from matplotlib.projections import register_projection
    register_projection(Axes3D)
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(11, 9), facecolor='#101724')
    ax = fig.add_subplot(111, projection='3d', facecolor='#101724')
    if len(order):
        intens = np.asarray(arrays['intensity'][order], float)
        intens = np.ma.masked_invalid(intens)
        ax.scatter(*xyz.T, c=intens, cmap='viridis', s=2, linewidths=0)
    half = camera['distance'] * np.tan(np.deg2rad(camera['fov_deg']/2))*.8
    for i, setter in enumerate((ax.set_xlim, ax.set_ylim, ax.set_zlim)):
        setter(camera['target'][i]-half, camera['target'][i]+half)
    ax.set_box_aspect((1,1,1)); ax.set_proj_type('persp', focal_length=1/np.tan(np.deg2rad(camera['fov_deg']/2)))
    ax.view_init(elev=camera['elevation_deg'], azim=camera['azimuth_deg'])
    ax.set_xlabel('X (m)'); ax.set_ylabel('Y (m)'); ax.set_zlabel('Z (m)')
    ax.set_title(f'BLIND raw ROI · {len(order)}/{int(valid.sum())} valid selected slots displayed\n'
                 'No algorithm labels, scores or human answer shown', color='white')
    ax.tick_params(colors='#bac6d6')
    fig.savefig(output, dpi=130, facecolor=fig.get_facecolor()); plt.close(fig)
    payload = dict(xyz=xyz.tolist(), ids=[int(x) for x in arrays['raw_slot_id'][order]],
                   intensity=_json_numbers(arrays['intensity'][order]), camera=camera,
                   finite_roi_count=int(valid.sum()), blind=True,
                   source_npz='blind review raw evidence; see case.json for source provenance')
    return payload


def export_review(npz_path, output_dir, *, roi=None, view=None, blind=False,
                  reviewer=None, confidence=None, human_label=None, note=None, max_points=12000):
    npz_path, out = Path(npz_path).resolve(), Path(output_dir).resolve()
    if not out.is_relative_to(ROOT):
        raise ValueError('All review outputs must remain under opdf_v1')
    if out.exists():
        raise FileExistsError('Refusing to overwrite a prior review case')
    if max_points < 1:
        raise ValueError('max_points must be positive')
    if confidence is not None and (not np.isfinite(confidence) or not 0 <= confidence <= 1):
        raise ValueError('Human confidence must be a supplied value between 0 and 1')
    if human_label is not None and (human_label not in ('E','A','U','G') or not reviewer or confidence is None):
        raise ValueError('A human label requires actual reviewer and confidence inputs')
    arrays = load_result(npz_path)
    exact = exact_selection(arrays, roi)
    display_indices = exact[np.isfinite(arrays['xyz'][exact]).all(axis=1) & arrays['valid_xyz_mask'][exact]]
    camera = normalize_view(view, arrays['xyz'][display_indices])
    side = npz_path.with_suffix('.json')
    meta = json.loads(side.read_text()) if side.exists() else {}
    source = meta.get('metadata', meta)
    config = npz_path.parent.parent/'config_snapshot.yaml'
    out.mkdir(parents=True)
    # Every slot-aligned feature is exported in unblinded mode. Blind exports raw
    # evidence only; it does not include a hidden answer in the embedded HTML/NPZ.
    keys = ('xyz', 'intensity', 'valid_xyz_mask', 'raw_slot_id') if blind else tuple(arrays)
    selected = {k: arrays[k][exact] for k in keys if np.asarray(arrays[k]).ndim and len(arrays[k]) == len(arrays['xyz'])}
    np.savez_compressed(out/'exact_slots.npz', **selected)
    np.save(out/'raw_slot_ids.npy', arrays['raw_slot_id'][exact])
    ids_hash = hashlib.sha256(arrays['raw_slot_id'][exact].astype('<u8').tobytes()).hexdigest()
    case = dict(version=1, created_utc=datetime.now(timezone.utc).isoformat(),
                source_npz=str(npz_path), source_npz_sha256=sha(npz_path),
                source_sidecar=str(side) if side.exists() else None,
                source_sidecar_sha256=sha(side) if side.exists() else None,
                source_message_sha256=source.get('raw_message_sha256'),
                source_cache_path=source.get('source_cache_path'),
                source_cache_sha256=source.get('source_cache_sha256'),
                source_bag=source.get('source_bag'), source_record_locator=source.get('source_record_locator'),
                source_frame_id=source.get('frame_id'), source_header_stamp_ns=source.get('header_stamp_ns'),
                config_path=str(config) if config.exists() else None,
                config_file_sha256=sha(config) if config.exists() else None,
                heuristic_config_sha256=meta.get('config_sha256'),
                roi=roi, camera=camera, blind=bool(blind), exact_selected_count=len(exact),
                selected_invalid_xyz_count=int((~(np.isfinite(arrays['xyz'][exact]).all(axis=1) & arrays['valid_xyz_mask'][exact])).sum()),
                exact_raw_slot_ids_sha256=ids_hash, feature_keys=list(selected),
                display_max_points=max_points, semantic_truth='UNKNOWN_NO_INDEPENDENT_GT')
    write_json(out/'case.json', case); write_json(out/'view.json', camera)
    review = dict(case_id=out.name, source_npz_sha256=sha(npz_path),
                  exact_raw_slot_ids_sha256=ids_hash, reviewer_id=reviewer,
                  confidence=confidence, human_label=human_label, note=note,
                  status='USER_SUPPLIED_ROI_LABEL' if human_label else 'PENDING_HUMAN_REVIEW',
                  scope='selected ROI, not all frame; confidence is human self-report, not calibrated',
                  independent_reference_certified=False)
    write_json(out/'human_review.json', review)
    if blind:
        payload = _blind_screenshot(arrays, exact, out/'review.png', camera, max_points)
        (out/'review.html').write_text(_viewer_html(payload))
    else:
        render_frame(npz_path, output_png=out/'review.png', output_html=out/'review.html',
                     view=camera, max_points=max_points, roi={'raw_slot_ids': [int(x) for x in arrays['raw_slot_id'][exact]]})
        # Decode named reason bits from actual source diagnostics where provided.
        modules = meta.get('diagnostics', {}).get('modules', {})
        reason_definitions = {k:v for k,v in modules.items() if isinstance(v,dict)}
        write_json(out/'reason_definitions.json', reason_definitions)
    return case


def regress_case(case_path, output_dir):
    """Re-run unchanged config/cache with current code; no bag IO or tuning."""
    p = Path(case_path)
    case = json.loads((p/'case.json' if p.is_dir() else p).read_text())
    old = Path(case['source_npz']); cache = Path(case.get('source_cache_path') or '')
    cfg_path = Path(case.get('config_path') or '')
    if sha(old) != case['source_npz_sha256']:
        raise ValueError('Original result changed since case creation')
    if not cache.is_file() or not cfg_path.is_file():
        raise ValueError('Regression requires original serialized cache and frozen config')
    if sha(cache) != case['source_cache_sha256'] or sha(cfg_path) != case['config_file_sha256']:
        raise ValueError('Original cache/config hash changed')
    import yaml
    from opdf.io_rosbag import load_cached_frame
    from opdf.pipeline import process_frame, config_hash
    cfg = yaml.safe_load(cfg_path.read_text())
    if config_hash(cfg) != case['heuristic_config_sha256']:
        raise ValueError('Config canonical hash does not match original result')
    frame = load_cached_frame(cache)
    if frame.metadata().get('raw_message_sha256') != case['source_message_sha256']:
        raise ValueError('Regression raw message identity mismatch')
    side = json.loads(old.with_suffix('.json').read_text())
    ablation = side.get('diagnostics', {}).get('ablation', 'full')
    result = process_frame(frame, cfg, ablation=ablation)
    out = Path(output_dir).resolve()
    if not out.is_relative_to(ROOT) or out.exists():
        raise ValueError('Regression output must be a new directory under opdf_v1')
    out.mkdir(parents=True)
    new_path = out/'rerun.npz'; np.savez_compressed(new_path, **result['arrays'])
    write_json(new_path.with_suffix('.json'), {'metadata':result['metadata'],'diagnostics':result['diagnostics'],
                'status':result['diagnostics']['status'],'config_sha256':config_hash(cfg)})
    before, after = load_result(old), load_result(new_path)
    if not np.array_equal(before['raw_slot_id'], after['raw_slot_id']):
        raise ValueError('Regression index domain changed; cannot silently compare')
    selected = exact_selection(before, case.get('roi'))
    changed = before['labels'] != after['labels']
    delta = {k:v for k,v in dict(raw_slot_id=before['raw_slot_id'],
             old_labels=before['labels'],new_labels=after['labels'],
             old_reason=before['reason_code'],new_reason=after['reason_code']).items()}
    np.savez_compressed(out/'changes.npz', **delta)
    summary = dict(source_case=str(p.resolve()), raw_message_sha256=case['source_message_sha256'],
                   config_sha256=config_hash(cfg), ablation=ablation,
                   full_frame_changed_labels=int(changed.sum()), selected_roi_changed_labels=int(changed[selected].sum()),
                   full_frame_changed_reason_codes=int((before['reason_code'] != after['reason_code']).sum()),
                   new_status=result['diagnostics']['status'], measurement_type='BEHAVIOR_REGRESSION_NOT_ACCURACY',
                   code_sha256={str(q.relative_to(ROOT)):sha(q) for q in sorted((ROOT/'opdf').glob('*.py'))})
    write_json(out/'regression.json', summary)
    if case.get('blind'):
        payload = _blind_screenshot(after, selected, out/'rerun.png', case['camera'], case['display_max_points'])
        (out/'rerun.html').write_text(_viewer_html(payload))
    else:
        render_frame(new_path, output_png=out/'rerun.png', output_html=out/'rerun.html', view=case['camera'],
                     roi=case.get('roi'), max_points=case['display_max_points'])
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('npz', nargs='?'); p.add_argument('--output', required=True)
    p.add_argument('--bbox', nargs=6, type=float); p.add_argument('--slots', nargs='+', type=int)
    p.add_argument('--slots-file', help='JSON array of exact raw_slot_id integers')
    p.add_argument('--view'); p.add_argument('--blind', action='store_true'); p.add_argument('--max-points', type=int, default=12000)
    p.add_argument('--reviewer'); p.add_argument('--confidence', type=float)
    p.add_argument('--human-label', choices=['E','A','U','G']); p.add_argument('--note')
    p.add_argument('--regress', help='Existing case directory or case.json; uses unchanged frozen cache/config')
    a = p.parse_args()
    if a.regress:
        print(json.dumps(regress_case(a.regress, a.output), indent=2)); return
    if not a.npz:
        p.error('npz is required unless --regress is supplied')
    slots = json.loads(Path(a.slots_file).read_text()) if a.slots_file else a.slots
    roi = {k:v for k,v in dict(bbox=a.bbox,raw_slot_ids=slots).items() if v is not None}
    print(json.dumps(export_review(a.npz, a.output, roi=roi, view=a.view, blind=a.blind,
                    reviewer=a.reviewer, confidence=a.confidence, human_label=a.human_label,
                    note=a.note, max_points=a.max_points), indent=2))


if __name__ == '__main__':
    main()
