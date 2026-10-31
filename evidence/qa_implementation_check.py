#!/usr/bin/env python3
"""Independent OPDF implementation audit; one original message, one real rerun."""
import os,sys,json,hashlib,struct,time,importlib.util
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.cache/qa_matplotlib'))
os.environ.setdefault('OPENBLAS_NUM_THREADS','2');os.environ.setdefault('OMP_NUM_THREADS','2')
import numpy as np
import yaml
from opdf.io_rosbag import load_cached_frame
from opdf.pipeline import process_frame,config_hash

E=ROOT/'evidence';O=ROOT/'outputs/v1b_real9_final'
manifest=json.loads((ROOT/'manifest.json').read_text())
entry=next(x for x in manifest['frames'] if x['key']=='middle_seq245847')
cache=ROOT/entry['path'];cached=cache.read_bytes();bag=Path(manifest['source_bag']);before=bag.stat()
with bag.open('rb') as f:
 head=f.read(65536);f.seek(entry['locator']['message_file_offset']);raw=f.read(len(cached))
assert raw==cached and hashlib.sha256(raw).hexdigest()==entry['sha256']
fp=manifest['source_fingerprint']
assert hashlib.sha256(head).hexdigest()==fp['head_sha256'] and before.st_size==fp['size_bytes'] and before.st_mtime_ns==fp['mtime_ns']
# QA's small independent serialized-PointCloud2 parser.
i=0
def U():
 global i
 v=struct.unpack_from('<I',raw,i)[0];i+=4;return v
def S():
 global i
 n=U();v=raw[i:i+n].decode();i+=n;return v
seq=U();sec=U();ns=U();frame_id=S();h=U();w=U();fields=[]
for _ in range(U()):
 name=S();offset=U();dt=raw[i];i+=1;count=U();fields.append(dict(name=name,offset=offset,datatype=dt,count=count))
big=bool(raw[i]);i+=1;step=U();row=U();n=U();data=raw[i:i+n];i+=n;dense=bool(raw[i]);i+=1
assert i==len(raw) and n==h*row and not big
xyz=np.column_stack([np.ndarray((h,w),dtype='<f4',buffer=data,offset=o,strides=(row,step)).ravel()for o in (0,4,8)])
valid=np.isfinite(xyz).all(1)
f=load_cached_frame(cache)
assert np.array_equal(f.xyz,xyz,equal_nan=True) and np.array_equal(valid,f.valid_xyz_mask)
assert np.array_equal(f.raw_slot_id,np.arange(h*w,dtype=np.uint64))
assert f.from_image(f.to_image(f.point_bytes())).tobytes()==f.point_bytes().tobytes()
cfg=yaml.safe_load((O/'config_snapshot.yaml').read_text());t=time.perf_counter();rerun=process_frame(f,cfg);elapsed=time.perf_counter()-t
np.savez_compressed(E/'qa_real_cache_rerun.npz',**rerun['arrays'])
with np.load(O/'frames'/f"{entry['key']}.npz") as z:
 same={k:np.array_equal(z[k],rerun['arrays'][k],equal_nan=True)for k in ['labels','reason_code','raw_slot_id','score_e','score_a','available_e','available_a']}
assert all(same.values()) and rerun['diagnostics']['status']=='OK'

counts=np.zeros(5,dtype=np.int64);slots=0;nv=0;rows=[]
for path in sorted((O/'frames').glob('*.npz')):
 with np.load(path)as z:
  finite=np.isfinite(z['xyz']).all(1)&z['valid_xyz_mask'];labels=z['labels']
  assert np.array_equal(labels==0,~finite)
  assert np.array_equal(z['raw_slot_id'],np.arange(len(labels),dtype=np.uint64))
  cc=np.bincount(labels,minlength=5);counts+=cc;slots+=len(labels);nv+=int(finite.sum())
  side=json.loads(path.with_suffix('.json').read_text());assert side['status']=='OK' and side['no_independent_gt']
  assert side['config_sha256']==config_hash(cfg)
  rows.append({'frame':path.stem,'slots':len(labels),'valid':int(finite.sum()),'counts':cc.tolist()})
summary=json.loads((O/'run_summary.json').read_text())
assert slots==summary['total_slots'] and nv==summary['valid_xyz_count'] and counts[1:].tolist()==[summary['counts'][x]for x in 'eaug']

# Full-slot ROI export checks; display cap must not truncate the evidence.
cases=[]
for d in sorted((O/'cases').iterdir()):
 if not d.is_dir()or not(d/'case.json').is_file():continue
 c=json.loads((d/'case.json').read_text());human=json.loads((d/'human_review.json').read_text())
 with np.load(c['source_npz'])as z, np.load(d/'exact_slots.npz')as e:
  ids=e['raw_slot_id'];pos=np.searchsorted(z['raw_slot_id'],ids)
  assert len(ids)==c['exact_selected_count'] and np.array_equal(z['raw_slot_id'][pos],ids)
  assert all(np.array_equal(e[k],z[k][pos],equal_nan=True)for k in e.files)
  expected={k for k in z.files if z[k].ndim and len(z[k])==len(z['xyz'])}
  assert set(e.files)==expected
  assert {'labels','score_e','score_a','reason_code'}<=set(e.files)
  feature_count=len(e.files)
 assert human['reviewer_id'] is None and human['confidence'] is None and human['human_label'] is None
 view=json.loads((d/'review.view.json').read_text())
 assert view['camera']==c['camera'] and view['selected_count']<=c['display_max_points']
 cases.append({'name':d.name,'full_slot_count':c['exact_selected_count'],'aligned_feature_count':feature_count,'display_selected_count':view['selected_count'],'human_fields_unfilled':True,'camera_matches':True})

spec=importlib.util.spec_from_file_location('qa_review',ROOT/'scripts/review_roi.py');review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)
# Actual real-data blind case with source A/E/U/G mixed slots, no invented reviewer.
source=O/'frames/middle_seq245847.npz'
with np.load(source)as z:
 chosen=[int(np.flatnonzero(z['labels']==k)[0])for k in [1,2,3,4]]
blind=review.export_review(source,E/'qa_blind_real_case',roi={'raw_slot_ids':chosen},blind=True,max_points=2)
text=(E/'qa_blind_real_case/review.html').read_text();payload=json.loads(text.split('<script id="opdf-data" type="application/json">')[1].split('</script>')[0])
assert not({'labels','score_e','score_a','reason_code'}&set(payload))
with np.load(E/'qa_blind_real_case/exact_slots.npz')as z:assert set(z.files)=={'xyz','intensity','valid_xyz_mask','raw_slot_id'} and len(z['xyz'])==4
assert blind['exact_selected_count']==4
after=bag.stat();assert(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
out={'date_local':'2026-10-31','one_original_payload_bytes_read':len(raw),'bag_fingerprint_head_bytes_read':len(head),
 'source_bag':str(bag),'source_message_offset':entry['locator']['message_file_offset'],'source_message_sha256':entry['sha256'],
 'original_equals_exact_cache':True,'independent_original_decode':{'seq':seq,'height':h,'width':w,'finite_xyz':int(valid.sum()),'fields':fields},
 'cache_rerun':{'frame':entry['key'],'elapsed_seconds':elapsed,'equality':same,'status':rerun['diagnostics']['status']},
 'all9_behavior_counts':{'slots':slots,'valid':nv,'INVALID':int(counts[0]),'E':int(counts[1]),'A':int(counts[2]),'U':int(counts[3]),'G':int(counts[4]),'independent_gt':False},
 'all9_per_frame':rows,'real_cases':cases,'real_blind_case':{'path':'evidence/qa_blind_real_case','all4_exact_slots_exported':True,'display_cap':2,'no_label_score_reason_payload':True},
 'bag_size_mtime_unchanged':True,'production_nodes_started':False,'training_executed':False,'all_checks_pass':True}
(E/'qa_implementation_check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False,indent=2))
