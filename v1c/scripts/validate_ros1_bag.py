#!/usr/bin/env python3
"""Read every native ROS1 bag message; independently check source slots and colors."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse,hashlib,io,json,time
from types import SimpleNamespace
from sensor_msgs.msg import PointCloud2
import numpy as np
import rosbag
from opdf_c.sequence_io import CROOT,TOPICS,FIELDS,PALETTE,STAGE2,write_json,inside

def same_float_values(a,b):
 return a.shape==b.shape and np.all((a==b)|(np.isnan(a)&np.isnan(b)))

def native_source_frame(cache,expected_sha):
 raw=cache.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=expected_sha:raise ValueError('source cache SHA mismatch')
 msg=PointCloud2();msg.deserialize(raw);n=msg.height*msg.width;fields={f.name:f for f in msg.fields};prefix='>'if msg.is_bigendian else'<'
 def channel(name):
  f=fields[name]
  if f.datatype not in (7,8)or f.count!=1:raise ValueError('source numeric field unsupported')
  dtype=prefix+('f4'if f.datatype==7 else'f8')
  return np.ndarray((msg.height,msg.width),dtype=np.dtype(dtype),buffer=msg.data,offset=f.offset,strides=(msg.row_step,msg.point_step)).reshape(-1).copy()
 xyz=np.column_stack([channel(k)for k in ('x','y','z')]);schema=[{'name':f.name,'offset':f.offset,'datatype':f.datatype,'count':f.count}for f in msg.fields]
 return SimpleNamespace(xyz=xyz,intensity=channel('intensity'),raw_slot_id=np.arange(n,dtype=np.uint64),valid_xyz_mask=np.isfinite(xyz).all(1),field_schema=schema,height=msg.height,width=msg.width,point_step=msg.point_step,row_step=msg.row_step,is_bigendian=msg.is_bigendian,is_dense=msg.is_dense,frame_id=msg.header.frame_id)

def independent_expected_rgb(arrays,layer,slot):
 labels=arrays['labels'][slot]
 if layer in STAGE2:
  score_key,av_key=STAGE2[layer];score=arrays[score_key][slot];av=arrays[av_key][slot]&np.isfinite(score);v=np.clip(np.nan_to_num(score),0,1);rgb=np.full((len(slot),3),100,np.uint8)
  rgb[av,0]=(255*v[av]).astype(np.uint8);rgb[av,1]=(80*(1-v[av])).astype(np.uint8);rgb[av,2]=(255*(1-v[av])).astype(np.uint8)
 else:
  rgb=np.zeros((len(slot),3),np.uint8)
  for label,color in PALETTE.items():rgb[labels==label]=color
 return (rgb[:,0].astype(np.uint32)<<16)|(rgb[:,1].astype(np.uint32)<<8)|rgb[:,2].astype(np.uint32)

def expected_slots(arrays,layer):
 valid=arrays['valid_xyz_mask']&np.isfinite(arrays['xyz']).all(1);label=arrays['labels']
 if layer=='entity_only':mask=valid&(label==1)
 elif layer=='retained':mask=valid&((label==1)|(label==3))
 elif layer=='aerosol_strong':mask=valid&(label==2)
 elif layer=='ground':mask=valid&(label==4)
 elif layer=='unknown':mask=valid&(label==3)
 elif layer=='nonground':mask=valid&(label!=4)
 else:mask=valid
 return np.flatnonzero(mask)

def validate(run,bagpath=None):
 run=inside(run);index=json.loads((run/'debug_frame_index.json').read_text());manifest=json.loads((run/'input_manifest.json').read_text());entries={r['record_stamp_ns']:r for r in manifest['frames']};path=Path(bagpath or index['bag_path']);started=time.perf_counter();records=[];failures=[];seen=set();current=None;context=None
 try:
  with rosbag.Bag(str(path),'r')as bag:
   info=bag.get_type_and_topic_info()[1]
   if set(info)!=set(TOPICS):raise ValueError('bag topic whitelist mismatch')
   for topic,msg,stamp in bag.read_messages():
    rn=stamp.to_nsec();key=(rn,topic)
    try:
     if rn not in entries or key in seen:raise ValueError('unexpected/duplicate frame-topic record')
     seen.add(key);entry=entries[rn]
     if current!=rn:
      cache=Path(manifest['output_dir'])/entry['path'];frame=native_source_frame(cache,entry['sha256'])
      with np.load(run/'frames'/f'{entry["key"]}.npz',allow_pickle=False)as z:arrays={k:z[k]for k in z.files}
      if not same_float_values(arrays['xyz'],frame.xyz)or not same_float_values(arrays['intensity'],frame.intensity)or not np.array_equal(arrays['raw_slot_id'],frame.raw_slot_id)or not np.array_equal(arrays['valid_xyz_mask'],frame.valid_xyz_mask):raise ValueError('NPZ source slot data differs from cached raw frame')
      context=(cache,frame,arrays);current=rn
     cache,frame,arrays=context
     if msg.header.seq!=entry['seq']or msg.header.stamp.to_nsec()!=entry['header_stamp_ns']or msg.header.frame_id!=frame.frame_id:raise ValueError('source header/seq/frame mismatch')
     fields=[{'name':x.name,'offset':x.offset,'datatype':x.datatype,'count':x.count}for x in msg.fields]
     if topic=='/opdf_v1/raw':
      b=io.BytesIO();msg.serialize(b);sha=hashlib.sha256(b.getvalue()).hexdigest()
      if sha!=entry['sha256']or b.getvalue()!=cache.read_bytes():raise ValueError('raw whole serialized source bytes mismatch')
      if fields!=frame.field_schema or (msg.height,msg.width,msg.point_step,msg.row_step,msg.is_bigendian,msg.is_dense)!=(frame.height,frame.width,frame.point_step,frame.row_step,frame.is_bigendian,frame.is_dense):raise ValueError('raw schema/shape/stride/flags mismatch')
      count=frame.height*frame.width
     else:
      layer=topic.rsplit('/',1)[1];slot=expected_slots(arrays,layer);count=len(slot)
      if fields!=FIELDS or (msg.height,msg.width,msg.point_step,msg.row_step,msg.is_bigendian,msg.is_dense)!=(1,count,24,count*24,False,True):raise ValueError('derived field/count/stride/flags mismatch')
      if len(msg.data)!=count*24:raise ValueError('derived data length mismatch')
      dt=np.dtype({'names':['x','y','z','intensity','rgb_bits','raw_slot_id'],'formats':['<f4']*4+['<u4']*2,'offsets':[0,4,8,12,16,20],'itemsize':24});points=np.frombuffer(msg.data,dtype=dt)
      if not np.array_equal(points['raw_slot_id'],frame.raw_slot_id[slot].astype(np.uint32)):raise ValueError('derived raw_slot membership/order mismatch')
      for col,name in enumerate(('x','y','z')):
       if points[name].tobytes()!=frame.xyz[slot,col].astype('<f4').tobytes():raise ValueError('derived coordinate bit mismatch '+name)
      if points['intensity'].tobytes()!=frame.intensity[slot].astype('<f4').tobytes():raise ValueError('derived intensity bit mismatch')
      if not np.array_equal(points['rgb_bits'],independent_expected_rgb(arrays,layer,slot)):raise ValueError('derived packed RGB mismatch')
      sha=hashlib.sha256(msg.data).hexdigest()
     records.append({'key':entry['key'],'topic':topic,'record_stamp_ns':rn,'header_stamp_ns':msg.header.stamp.to_nsec(),'seq':msg.header.seq,'points':count,'data_or_serialized_sha256':sha,'all_fields_values_slots_colors_timestamps_checked':True,'status':'PASS'})
    except Exception as e:failures.append({'topic':topic,'record_stamp_ns':rn,'error':type(e).__name__+': '+str(e)})
  expected={(r['record_stamp_ns'],t)for r in manifest['frames']for t in TOPICS}
  if seen!=expected:failures.append({'missing_or_extra_frame_topic_records':len(expected.symmetric_difference(seen))})
 except Exception as e:failures.append({'fatal':type(e).__name__+': '+str(e)})
 result={'status':'PASS'if not failures else'FAIL','bag_path':str(path),'frames_expected':len(entries),'messages_expected':len(entries)*len(TOPICS),'messages_validated':len(records),'failures':failures,'elapsed_seconds':time.perf_counter()-started,'method':'native rosbag read_messages for every message; raw compares original serialized cache; derived compares independent label-slot subsets and source coordinates/intensity plus packed RGB/schema/header/record','ros_nodes_started':False,'records':records};write_json(run/'ros1_bag_validation.json',result);print(json.dumps({k:v for k,v in result.items()if k!='records'},ensure_ascii=False),flush=True)
 if failures:raise SystemExit(2)
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,default=CROOT/'outputs/v1b_continuous30');p.add_argument('--bag',type=Path);a=p.parse_args();validate(a.run,a.bag)
