#!/usr/bin/env python3
"""Run OPDF-V1-B on bounded, provenance-bearing real bag caches."""
from pathlib import Path
import argparse
import csv
import datetime
import hashlib
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.cache/matplotlib'))
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
os.environ.setdefault('OMP_NUM_THREADS', '2')
import numpy as np
import yaml
from opdf.io_rosbag import load_cached_frame
from opdf.pipeline import process_frame, json_safe, config_hash, disabled_evidence
from opdf import decision
from opdf.visualization import render_frame
from opdf.evaluation import write_run_report


def write_json(path, value):
    Path(path).write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2, allow_nan=False))


def behavior(labels, valid):
    out = {'slots': len(labels), 'valid': int(valid.sum())}
    for k, name in enumerate(('INVALID', 'E', 'A', 'U', 'G')):
        out[name] = int((labels == k).sum())
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', type=Path, default=ROOT / 'manifest.json')
    ap.add_argument('--config', type=Path, default=ROOT / 'configs/v1b.yaml')
    ap.add_argument('--max-frames', type=int, default=9)
    ap.add_argument('--run-id')
    ap.add_argument('--render', action='store_true')
    ap.add_argument('--ablations', action='store_true')
    ap.add_argument('--sensitivity', action='store_true')
    args = ap.parse_args()
    if not 1 <= args.max_frames <= 60:
        ap.error('max-frames must be 1..60')
    cfg = yaml.safe_load(args.config.read_text())
    manifest = json.loads(args.manifest.read_text())
    source_root = Path(manifest.get('output_dir', args.manifest.parent))
    rows = manifest['frames'][:args.max_frames]
    run_id = args.run_id or datetime.datetime.now().strftime('v1b_%Y%m%d_%H%M%S_') + config_hash(cfg)[:8]
    if Path(run_id).name != run_id:
        ap.error('run-id must be a single directory name')
    out = ROOT / 'outputs' / run_id
    out.mkdir(exist_ok=False)
    for sub in ('frames', 'figures', 'interactive'):
        (out / sub).mkdir()
    (out / 'config_snapshot.yaml').write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    write_json(out / 'input_manifest.json', manifest)
    write_json(out / 'method_sources.json', {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                           for p in sorted((ROOT / 'opdf').glob('*.py'))})
    viscfg = cfg.get('visualization', {})
    write_json(out / 'view.json', viscfg.get('view'))
    ablation_rows, sensitivity_rows, temporal_rows = [], [], []
    representative_windows = set()
    failures = []
    started = time.perf_counter()
    with (out / 'diagnostics.jsonl').open('w') as log:
        for entry in rows:
            cache = source_root / entry['path']
            if hashlib.sha256(cache.read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError(f'Cached source hash mismatch {cache}')
            frame = load_cached_frame(cache)
            result = process_frame(frame, cfg)
            key = entry['key']
            result['metadata'].update(source_cache_path=str(cache.resolve()),
                                      source_cache_sha256=entry['sha256'], window=entry.get('window'))
            meta = {'metadata': result['metadata'], 'diagnostics': result['diagnostics'],
                    'status': result['diagnostics']['status'], 'method': 'OPDF-V1-B',
                    'config_sha256': config_hash(cfg), 'no_independent_gt': True}
            path = out / 'frames' / f'{key}.npz'
            np.savez_compressed(path, **result['arrays'])
            write_json(path.with_suffix('.json'), meta)
            record = {'key': key, **meta, 'behavior': behavior(result['arrays']['labels'], frame.valid_xyz_mask)}
            log.write(json.dumps(json_safe(record), ensure_ascii=False, allow_nan=False) + '\n'); log.flush()
            if meta['status'] in ('ERROR', 'REJECT'):
                failures.append({'key': key, 'status': meta['status'], 'error': result['diagnostics'].get('error')})
            if args.render:
                render_frame(path, output_png=out / 'figures' / f'{key}_3d.png',
                             output_html=out / 'interactive' / f'{key}.html',
                             view=viscfg.get('view'), max_points=viscfg.get('max_points', 30000),
                             roi=viscfg.get('roi'))
            window = entry.get('window', key)
            temporal_rows.append({'key':key, 'window':window, 'seq':frame.seq,
                                  'header_stamp_ns':frame.header_stamp_ns, 'record_stamp_ns':frame.record_stamp_ns,
                                  'm4_available':False, 'reason':'NO_VERIFIED_EGO_TARGET_CORRESPONDENCE'})
            if window not in representative_windows and meta['status'] == 'OK':
                representative_windows.add(window)
                evidence = {prefix: {'arrays':{k.split('__', 1)[1]:v for k,v in result['arrays'].items()
                                              if k.startswith(prefix + '__')}, 'diagnostics':{}}
                            for prefix in ('ground', 'optical', 'geometry')}
                if args.ablations:
                    for name in ('B0', 'ground', 'ground_optical', 'ground_geometry', 'full'):
                        if name == 'B0':
                            labels = np.where(frame.valid_xyz_mask, 3, 0).astype(np.uint8)
                        else:
                            optical = evidence['optical'] if name in ('ground_optical','full') else disabled_evidence(frame, 'optical')
                            geometry = evidence['geometry'] if name in ('ground_geometry','full') else disabled_evidence(frame, 'geometry')
                            labels = decision.classify(frame, evidence['ground'], optical, geometry, cfg)['arrays']['labels']
                        ablation_rows.append({'key':key, 'ablation':name, 'scope':'same original slots; cached unchanged module evidence; behavior not accuracy',
                                              **behavior(labels,frame.valid_xyz_mask)})
                if args.sensitivity:
                    for shift in (-0.1, 0., 0.1):
                        import copy
                        variant = copy.deepcopy(cfg)
                        keys = ('aerosol_optical_min','aerosol_scan_discontinuity_min','aerosol_spatial_diffuse_min')
                        for k in keys:
                            variant['decision'][k] = float(np.clip(cfg['decision'][k] + shift, 0, 1))
                        rr = decision.classify(frame, evidence['ground'], evidence['optical'], evidence['geometry'], variant)
                        sensitivity_rows.append({'key':key,'threshold_shift':shift,'config_sha256':config_hash(variant),
                                                 'scope':'predefined debug gate perturbation, no GT optimum', **behavior(rr['arrays']['labels'],frame.valid_xyz_mask)})
            print(json.dumps({'frame':key,'status':meta['status'], **record['behavior']},ensure_ascii=False),flush=True)
    for name, table in [('ablations.csv',ablation_rows),('sensitivity.csv',sensitivity_rows)]:
        if table:
            with (out/name).open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    for i,row in enumerate(temporal_rows):
        previous=temporal_rows[i-1] if i else None
        row['delta_header_ns']=row['header_stamp_ns']-previous['header_stamp_ns'] if previous and previous['window']==row['window'] else None
        row['sequence_increment']=row['seq']-previous['seq'] if previous and previous['window']==row['window'] else None
    write_json(out/'m4_feasibility.json',{'available':False,'decision':'Keep V1-B, do not implement material-motion shortcut',
                                       'observations':temporal_rows,'unknown':['ego-motion validation','same-azimuth phase alignment','object rigid correspondence','per-point timing']})
    metrics=write_run_report(out)
    summary={'run_id':run_id,'source_bag':manifest['source_bag'],'actual_real_frames':len(rows),
             'config_sha256':config_hash(cfg),'failures':failures,'elapsed_total_seconds':time.perf_counter()-started,
             'compute_scope':'single frame V1-B only; no production B1 or supervised training',**metrics}
    write_json(out/'run_summary.json',summary)
    (ROOT/'outputs/latest_run.txt').write_text(run_id+'\n')
    print(json.dumps(json_safe(summary),ensure_ascii=False),flush=True)
    if failures:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
