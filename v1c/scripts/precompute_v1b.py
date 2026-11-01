#!/usr/bin/env python3
"""Run frozen single-frame V1-B on selected real consecutive caches; no tuning."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import argparse,csv,hashlib,json,os,shutil,time
CROOT=Path(__file__).resolve().parents[1];BROOT=CROOT.parent
sys.path[:0]=[str(CROOT),str(BROOT)]
os.environ['MPLCONFIGDIR']=str(CROOT/'evidence/matplotlib');os.environ.setdefault('OPENBLAS_NUM_THREADS','2');os.environ.setdefault('OMP_NUM_THREADS','2')
import numpy as np,yaml
from opdf.io_rosbag import load_cached_frame
from opdf.pipeline import process_frame,json_safe,config_hash
from opdf_c.sequence_io import write_json,inside,schema

def main():
 p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,default=CROOT/'samples/continuous30/manifest.json');p.add_argument('--output',type=Path,default=CROOT/'outputs/v1b_continuous30');a=p.parse_args();out=inside(a.output);out.mkdir(parents=True,exist_ok=False);(out/'frames').mkdir()
 frozen=json.loads((CROOT/'evidence/v1b_frozen_baseline.json').read_text());source_hashes={}
 for row in frozen['files']:
  rel=row['path']
  if rel.startswith('opdf/')and rel.endswith('.py')or rel=='configs/v1b.yaml':
   digest=hashlib.sha256((BROOT/rel).read_bytes()).hexdigest()
   if digest!=row['sha256']:raise ValueError('frozen baseline changed: '+rel)
   source_hashes[rel]=digest
 cfg=yaml.safe_load((BROOT/'configs/v1b.yaml').read_text());shutil.copyfile(BROOT/'configs/v1b.yaml',out/'config_snapshot.yaml');m=json.loads(a.manifest.read_text());write_json(out/'input_manifest.json',m);write_json(out/'method_sources.json',source_hashes);write_json(out/'schema.json',schema());rows=[];fail=[];started=time.perf_counter()
 with (out/'diagnostics.jsonl').open('w')as log:
  for entry in m['frames']:
   t=time.perf_counter();cache=Path(m['output_dir'])/entry['path'];frame=load_cached_frame(cache);read_ms=(time.perf_counter()-t)*1000
   if frame.source_fingerprint['raw_message_sha256']!=entry['sha256']:raise ValueError('manifest/cache hash differs')
   if frame.header_stamp_ns!=entry['header_stamp_ns']or frame.record_stamp_ns!=entry['record_stamp_ns']:raise ValueError('manifest/cache timestamps differ')
   t=time.perf_counter();r=process_frame(frame,cfg);compute_ms=(time.perf_counter()-t)*1000
   r['metadata'].update(source_cache_path=str(cache.resolve()),source_cache_sha256=entry['sha256'],window='continuous30')
   meta={'metadata':r['metadata'],'diagnostics':r['diagnostics'],'status':r['diagnostics']['status'],'method':'FROZEN_OPDF-V1-B','config_sha256':config_hash(cfg),'no_independent_gt':True}
   t=time.perf_counter();dest=out/'frames'/f'{entry["key"]}.npz';np.savez_compressed(dest,**r['arrays']);write_json(dest.with_suffix('.json'),json_safe(meta));serialize_ms=(time.perf_counter()-t)*1000
   labels=r['arrays']['labels'];row={'key':entry['key'],'seq':frame.seq,'header_stamp_ns':frame.header_stamp_ns,'record_stamp_ns':frame.record_stamp_ns,'status':meta['status'],'slots':len(labels),'finite':int(frame.valid_xyz_mask.sum()),**{k:int((labels==v).sum())for v,k in enumerate(['INVALID','E','A','U','G'])},'read_decode_ms':read_ms,'algorithm_compute_ms':compute_ms,'npz_json_serialize_ms':serialize_ms,**{f'module_{k}_ms':v for k,v in r['diagnostics']['timings_ms'].items()}}
   rows.append(row);log.write(json.dumps(json_safe({'behavior':row,**meta}),ensure_ascii=False,allow_nan=False)+'\n');log.flush();print(json.dumps(row),flush=True)
   if meta['status']!='OK':fail.append({'key':entry['key'],'status':meta['status']})
 with (out/'metrics.csv').open('w',newline='')as f:
  fields=sorted(set().union(*(r.keys()for r in rows)));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 summary={'status':'COMPLETE'if not fail else'FAILED','real_frames':len(rows),'source_manifest':str(a.manifest),'output_dir':str(out),'config_sha256':config_hash(cfg),'frozen_baseline_checked':True,'failures':fail,'elapsed_total_seconds':time.perf_counter()-started,'timing_scope':'offline cached decode, frozen algorithm compute, NPZ/JSON serialization separately; no bag writer/RViz timing here','totals':{k:sum(r[k]for r in rows)for k in ['slots','finite','INVALID','E','A','U','G']}}
 write_json(out/'run_summary.json',summary);print(json.dumps(summary),flush=True)
 if fail:raise SystemExit(2)
if __name__=='__main__':main()
