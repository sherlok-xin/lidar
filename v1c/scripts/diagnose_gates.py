#!/usr/bin/env python3
"""Read frozen NPZ features; emit gate evidence only inside V1-C, never retune."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
V1C = Path(__file__).resolve().parents[1]
ROOT = V1C.parent
sys.path.insert(0,str(V1C))

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
import numpy as np
import yaml
from opdf_c.gate_diagnostics import VERSION, frame_report


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def add_counts(left,right):
    """Aggregate counts only; never sum or average quantiles/rates as observations."""
    if left is None:
        left={}
    omit={'feature_summary','new_threshold','changed_parameter','diagnostic_only_no_deletion','ground_available_required'}
    for key,value in right.items():
        if key in omit or 'rate' in key:
            continue
        if isinstance(value,dict):left[key]=add_counts(left.get(key),value)
        elif isinstance(value,int) and not isinstance(value,bool):left[key]=left.get(key,0)+value
    return left


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames',required=True,type=Path)
    parser.add_argument('--config',type=Path,default=ROOT/'configs/v1b.yaml')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--dataset-tag',required=True)
    parser.add_argument('--seq',type=int,action='append',help='Existing saved seq only, no new extraction')
    parser.add_argument('--source-manifest',type=Path)
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(V1C) or out==V1C:
        raise ValueError('All diagnostic writes must be in a new V1-C subdirectory')
    if out.exists():raise FileExistsError(f'Refuse to overwrite diagnostic run: {out}')
    paths=sorted(args.frames.resolve().glob('*.npz'))
    selected=[]
    for p in paths:
        meta_path=p.with_suffix('.json')
        if not meta_path.exists():raise FileNotFoundError(meta_path)
        meta=json.loads(meta_path.read_text())
        if args.seq and meta.get('metadata',meta).get('seq') not in args.seq:continue
        selected.append((p,meta_path,meta))
    if not selected:raise ValueError('No completed saved NPZ frames selected; continuous data NOT_READY')
    cfg=yaml.safe_load(args.config.read_text())
    cfg_hash=hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for _,_,meta in selected:
        old_hash=meta.get('config_sha256',meta.get('diagnostics',{}).get('config_sha256'))
        if old_hash!=cfg_hash:raise ValueError(f'Frozen config hash mismatch: {old_hash} != {cfg_hash}')
    out.mkdir(parents=True)
    (out/'frames').mkdir()
    started=time.perf_counter()
    actual_command=[sys.executable,*sys.argv]
    records=[];aggregate={}
    with (out/'actual.log').open('w') as log:
        log.write('Command: '+repr(actual_command)+'\n')
        log.write('Dataset: '+args.dataset_tag+'; saved-feature diagnosis only, no new bag reads\n')
        for p,meta_path,meta in selected:
            t=time.perf_counter()
            with np.load(p,allow_pickle=False) as z:arrays={key:z[key] for key in z.files}
            load_ms=(time.perf_counter()-t)*1000
            t=time.perf_counter()
            report,gates,cfs=frame_report(arrays,cfg)
            compute_ms=(time.perf_counter()-t)*1000
            mapping={'raw_slot_id':arrays['raw_slot_id'],
                     'availability_pattern_OSP':gates['availability_pattern'],
                     'threshold_pattern_OSP':gates['threshold_pattern'],
                     'protection_pattern_NLE':gates['protection_pattern']}
            for name,cf in cfs.items():
                changed=cf['added']|cf['removed']
                mapping[name+'__raw_slot_id']=arrays['raw_slot_id'][changed]
                mapping[name+'__baseline_label']=arrays['labels'][changed]
                mapping[name+'__hypothetical_A_only_label']=np.where(cf['candidate_A'][changed],2,arrays['labels'][changed]).astype(np.uint8)
            report.update(source_npz=str(p),source_npz_sha256=sha(p),source_metadata_sha256=sha(meta_path),
                          source_message_sha256=meta.get('metadata',meta).get('raw_message_sha256'),
                          source_seq=meta.get('metadata',meta).get('seq'),dataset_tag=args.dataset_tag,
                          frozen_config_sha256=cfg_hash,
                          timings_ms={'saved_npz_load':load_ms,'diagnosis_compute':compute_ms})
            dump(out/'frames'/f'{p.stem}.json',report)
            np.savez_compressed(out/'frames'/f'{p.stem}_diagnostic_masks.npz',**mapping)
            for scope,groups in report['grouped'].items():
                aggregate[scope]=add_counts(aggregate.get(scope),groups['all'])
            entry={'key':p.stem,'source_seq':report['source_seq'],'array_count':len(arrays),
                   'source_npz_sha256':report['source_npz_sha256'],'reconstruction':report['reconstruction'],
                   'load_ms':load_ms,'diagnosis_compute_ms':compute_ms}
            records.append(entry)
            log.write(json.dumps(entry,ensure_ascii=False)+'\n');log.flush()
    summary={'version':VERSION,'created_utc':datetime.now(timezone.utc).isoformat(),
             'dataset_tag':args.dataset_tag,'frame_count':len(records),'frames':records,
             'all_exact_reconstruction':all(r['reconstruction']['exact_match'] for r in records),
             'frozen_config_sha256':cfg_hash,'config_file_sha256':sha(args.config),
             'actual_command':actual_command,'aggregate_count_only':aggregate,
             'aggregate_scope':'point-frame observations, not unique particles/obstacles',
             'counterfactuals':'single A-protection removal or one threshold minus 0.10; no formal labels/deletion filter',
             'diagnostic_only_no_deletion':True,'independent_GT':False,
             'total_elapsed_s':time.perf_counter()-started,
             'source_manifest':str(args.source_manifest.resolve()) if args.source_manifest else None,
             'source_manifest_sha256':sha(args.source_manifest) if args.source_manifest else None,
             'source_files_sha256':{str(x.relative_to(ROOT)):sha(x) for x in [
                 ROOT/'opdf/ground_lite.py',ROOT/'opdf/optical.py',ROOT/'opdf/geometry.py',ROOT/'opdf/decision.py',
                 V1C/'opdf_c/gate_diagnostics.py',Path(__file__)]}}
    dump(out/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ['dataset_tag','frame_count','all_exact_reconstruction','total_elapsed_s']}))


if __name__=='__main__':
    main()
