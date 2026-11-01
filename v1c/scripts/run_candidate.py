#!/usr/bin/env python3
"""Same-slot V1-C review-mask experiment using frozen V1-B saved features."""
from pathlib import Path
import argparse,copy,csv,hashlib,json,sys,time
sys.dont_write_bytecode=True
C=Path(__file__).resolve().parents[1];B=C.parent;sys.path[:0]=[str(C),str(B)]
import numpy as np
import yaml
from opdf.pipeline import config_hash
from opdf_c.suspect import compute,DEFAULT,VERSION,REASONS

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-run',type=Path,default=C/'outputs/v1b_continuous30')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--uniform-low',action='store_true');a=p.parse_args()
    out=a.output.resolve()
    if not out.is_relative_to(C) or out.exists():raise ValueError('Use a new output directory inside V1-C')
    base=yaml.safe_load((a.source_run/'config_snapshot.yaml').read_text());diag={**DEFAULT,'uniform_low_enabled':a.uniform_low}
    cfg={**copy.deepcopy(base),'method':VERSION,'diagnostic_candidate':diag}
    files=sorted((a.source_run/'frames').glob('*.npz'))
    if len(files)!=30:raise ValueError('This experiment requires the frozen continuous30 complete input')
    out.mkdir(parents=True);(out/'frames').mkdir()
    (out/'config_snapshot.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False))
    dump(out/'input_manifest.json',json.loads((a.source_run/'input_manifest.json').read_text()))
    dump(out/'method_sources.json',{str(f.relative_to(B)):sha(f) for f in [Path(__file__),C/'opdf_c/suspect.py',C/'opdf_c/gate_diagnostics.py']})
    rows=[];t0=time.perf_counter();changes=0;total=0
    with (out/'diagnostics.jsonl').open('w') as log:
        for f in files:
            t=time.perf_counter()
            with np.load(f,allow_pickle=False) as z:arrays={k:z[k] for k in z.files}
            source=json.loads(f.with_suffix('.json').read_text());load_ms=(time.perf_counter()-t)*1000
            if source['config_sha256']!=config_hash(base):raise ValueError('B input config mismatch')
            t=time.perf_counter();extra=compute(arrays,base,diag);mask_ms=(time.perf_counter()-t)*1000
            # Frozen source arrays are carried through verbatim, including labels,
            # reasons, scores and E+U/G masks; additive features are a separate layer.
            merged={**arrays,**extra};n=len(arrays['labels']);total+=n
            assert np.array_equal(merged['labels'],arrays['labels'])
            row={'key':f.stem,'seq':source['metadata']['seq'],'header_stamp_ns':source['metadata']['header_stamp_ns'],
                 'record_stamp_ns':source['metadata']['record_stamp_ns'],'slots':n,'valid':int(arrays['valid_xyz_mask'].sum()),
                 **{name:int((arrays['labels']==i).sum()) for i,name in enumerate(['INVALID','E','A','U','G'])},
                 'suspect_review_only':int(extra['aerosol_suspect_mask'].sum()),
                 'suspect_protected':int(extra['suspect_protected_mask'].sum()),
                 'entity_optical_conflict':int(extra['entity_optical_conflict_mask'].sum()),
                 'changed_labels':0,'changed_reasons':0,'base_npz_load_ms':load_ms,'extra_diagnostic_compute_ms':mask_ms}
            row.update({f'suspect_in_{name}':int((extra['aerosol_suspect_mask']&(arrays['labels']==i)).sum()) for i,name in enumerate(['INVALID','E','A','U','G'])})
            t=time.perf_counter();np.savez_compressed(out/'frames'/f.name,**merged)
            side=copy.deepcopy(source);side.update(method=VERSION,config_sha256=config_hash(cfg),
               base_config_sha256=config_hash(base),source_b_npz=str(f.resolve()),source_b_npz_sha256=sha(f),
               diagnostic_candidate={'status':'REVIEW_ONLY_NOT_DELETION','config':diag,'reason_bits':REASONS,
                                     'label_and_retention_semantics':'unchanged frozen V1-B'},no_independent_gt=True)
            dump((out/'frames'/f.name).with_suffix('.json'),side);row['serialize_ms']=(time.perf_counter()-t)*1000
            rows.append(row);log.write(json.dumps(row)+'\n');log.flush()
    with (out/'metrics.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary=dict(method=VERSION,frames=len(rows),same_original_slots=total,uniform_low_enabled=a.uniform_low,
                 config_sha256=config_hash(cfg),base_config_sha256=config_hash(base),
                 changed_labels=changes,changed_reasons=0,suspect_review_only=sum(r['suspect_review_only'] for r in rows),
                 entity_optical_conflict=sum(r['entity_optical_conflict'] for r in rows),
                 suspect_protected=sum(r['suspect_protected'] for r in rows),
                 elapsed_seconds=time.perf_counter()-t0,performance_scope='saved B feature reuse + additive mask + serialization; NOT full algorithm latency improvement',
                 no_independent_gt=True,suspect_authorizes_deletion=False,source_run=str(a.source_run.resolve()))
    dump(out/'run_summary.json',summary);print(json.dumps(summary))

if __name__=='__main__':main()
