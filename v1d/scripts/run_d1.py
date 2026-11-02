#!/usr/bin/env python3
"""D1 only: reuse frozen C thirty frames; preserve every original slot array."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
DROOT=Path(__file__).resolve().parents[1];BROOT=DROOT.parent
sys.path.insert(0,str(DROOT))
import os
os.environ['MPLCONFIGDIR']=str(DROOT/'evidence/matplotlib');os.environ['TMPDIR']=str(DROOT/'evidence/tmp');Path(os.environ['TMPDIR']).mkdir(parents=True,exist_ok=True)
os.environ.setdefault('OPENBLAS_NUM_THREADS','2');os.environ.setdefault('OMP_NUM_THREADS','2')
import argparse,csv,hashlib,json,shutil,time
import numpy as np,yaml
from opdf_d.ground_clutter import compute,ablate_upper

def dump(path,x):Path(path).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False))
def sha(a):return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
def quantiles(a):
 x=np.asarray(a);x=x[np.isfinite(x)]
 return {'n':int(len(x)),'p01_p10_p50_p90_p99':np.quantile(x,[.01,.10,.5,.9,.99]).tolist()}if len(x)else {'n':0,'p01_p10_p50_p90_p99':None}
def table(path,rows):
 with Path(path).open('w',newline='')as f:
  w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys()for r in rows))));w.writeheader();w.writerows(rows)

def main():
 p=argparse.ArgumentParser();p.add_argument('--source-run',type=Path,default=BROOT/'v1c/outputs/v1b_continuous30');p.add_argument('--output',type=Path,default=DROOT/'outputs/d1_ground');p.add_argument('--config',type=Path,default=DROOT/'configs/d1.yaml');a=p.parse_args();out=a.output.resolve()
 try:out.relative_to(DROOT)
 except ValueError:raise ValueError('all new outputs must be inside v1d')
 out.mkdir(parents=True,exist_ok=False);(out/'frames').mkdir();cfg=yaml.safe_load(a.config.read_text());shutil.copyfile(a.config,out/'config_snapshot.yaml');manifest=json.loads((a.source_run/'input_manifest.json').read_text());dump(out/'input_manifest.json',manifest)
 dump(out/'method_sources.json',{str(x.relative_to(DROOT)):hashlib.sha256(x.read_bytes()).hexdigest()for x in [DROOT/'opdf_d/ground_clutter.py',DROOT/'scripts/run_d1.py',a.config]})
 started=time.perf_counter();rows=[];abl=[];bands=[];distributions=[];failures=[]
 with (out/'diagnostics.jsonl').open('w')as log:
  for entry in manifest['frames']:
   key=entry['key'];source=a.source_run/'frames'/f'{key}.npz';t=time.perf_counter()
   with np.load(source,allow_pickle=False)as z:base={k:z[k]for k in z.files}
   meta=json.loads(source.with_suffix('.json').read_text());basehash={k:sha(v)for k,v in base.items()};read_ms=(time.perf_counter()-t)*1000
   t=time.perf_counter();r=compute(base,meta,cfg);compute_ms=(time.perf_counter()-t)*1000;arrays=r['arrays'];diag=r['diagnostics']
   if set(base)-set(arrays):raise ValueError('original arrays missing')
   if any(arrays[k].dtype!=v.dtype or arrays[k].shape!=v.shape or sha(arrays[k])!=basehash[k]for k,v in base.items()):raise ValueError('original array modified')
   valid=base['valid_xyz_mask']&np.isfinite(base['xyz']).all(1);n=len(valid)
   if any(np.asarray(v).ndim==0 or len(v)!=n for v in arrays.values()):raise ValueError('array not original-slot aligned')
   if not np.array_equal(arrays['d1__nonground_strict_mask'],valid&~arrays['d1__ground_core_mask']):raise ValueError('strict mask partition violation')
   if not np.array_equal(arrays['d1__nonground_display_mask'],arrays['d1__nonground_strict_mask']&~arrays['d1__low_clutter_mask']):raise ValueError('display partition violation')
   rmeta={**meta,'method':'OPDF-V1-D1-DISPLAY','original_labels_unchanged':True,'source_v1b_npz':str(source.resolve()),'source_v1b_npz_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_original_array_sha256':basehash,'d1_config_sha256':hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'d1_diagnostics':diag}
   t=time.perf_counter();dest=out/'frames'/f'{key}.npz';np.savez_compressed(dest,**arrays);dump(dest.with_suffix('.json'),rmeta);write_ms=(time.perf_counter()-t)*1000
   t=time.perf_counter()
   with np.load(dest,allow_pickle=False)as z:
    if any(sha(z[k])!=basehash[k]for k in base):raise ValueError('on-disk original array readback mismatch')
   verify_ms=(time.perf_counter()-t)*1000
   row={'key':key,'seq':entry['seq'],'header_stamp_ns':entry['header_stamp_ns'],'record_stamp_ns':entry['record_stamp_ns'],'status':diag['status'],**diag['counts'],'original_arrays_count':len(base),'original_arrays_preserved':True,'read_hash_ms':read_ms,'compute_ms':compute_ms,'serialize_ms':write_ms,'original_arrays_readback_ms':verify_ms};rows.append(row)
   for upper in cfg['d1']['upper_ablation_m']:
    masks=ablate_upper(arrays,lower_m=cfg['d1']['ground_lower_m'],upper_m=upper);abl.append({'key':key,'seq':entry['seq'],'only_changed_parameter':'ground_upper_m','upper_m':upper,'finite':int(valid.sum()),'fixed_local_evidence':True,**{k:int(v.sum())for k,v in masks.items()}})
   rr=np.linalg.norm(base['xyz'],axis=1)
   for lo,hi,name in [(0,10,'0_10m'),(10,20,'10_20m'),(20,40,'20_40m'),(40,np.inf,'40plus_m')]:
    take=valid&(rr>=lo)&(rr<hi);bands.append({'key':key,'range_band':name,'finite':int(take.sum()),**{k:int((take&arrays['d1__'+k]).sum())for k in ['ground_available','local_model_used','ground_core_mask','low_clutter_mask','nonground_strict_mask','nonground_display_mask','hard_structure_protect_mask']}})
   distributions.append({'key':key,'range_finite_m':quantiles(rr[valid]),'global_height_available_m':quantiles(arrays['d1__global_anchor_height']),'local_height_available_m':quantiles(arrays['d1__local_height']),'local_correction_m':quantiles(arrays['d1__local_ground_correction']),'local_fit_seed_residual_mad_point_weighted_m':quantiles(arrays['d1__local_fit_mad']),'core_local_height_m':quantiles(arrays['d1__local_height'][arrays['d1__ground_core_mask']]),'small_ball_count_candidate_points':quantiles(arrays['d1__small_ball_count'][arrays['d1__cluster_id']>=0]),'large_ball_count_candidate_points':quantiles(arrays['d1__large_ball_count'][arrays['d1__cluster_id']>=0])})
   if diag['status']!='OK':failures.append({'key':key,'status':diag['status']})
   log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush();print(json.dumps(row),flush=True)
 table(out/'metrics.csv',rows);table(out/'upper_ablation.csv',abl);table(out/'range_bands.csv',bands);dump(out/'distributions.json',distributions)
 totalkeys=['finite','ground_available','local_model_used','ground_core','low_clutter','nonground_strict','nonground_display','hard_structure_protected','risk_unknown'];summary={'status':'COMPLETE'if not failures else'COMPLETED_WITH_ABSTENTIONS','real_frames':len(rows),'failures':failures,'totals':{k:sum(r[k]for r in rows)for k in totalkeys},'all_original_arrays_preserved':all(r['original_arrays_preserved']for r in rows),'source_run':str(a.source_run.resolve()),'elapsed_seconds':time.perf_counter()-started,'timing_median_ms':{k:float(np.median([r[k]for r in rows]))for k in ['read_hash_ms','compute_ms','serialize_ms','original_arrays_readback_ms']},'original_labels_unchanged':True,'scope':'D1 display candidates; no production occupancy, no material truth, no D2'}
 dump(out/'run_summary.json',summary);print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
