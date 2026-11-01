#!/usr/bin/env python3
"""Offline ROS1 debug bag writer. Never initializes a ROS node/master."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse,hashlib,io,json,time
import numpy as np
import rosbag,rospy
from sensor_msgs.msg import PointCloud2,PointField
from std_msgs.msg import Header
from opdf_c.sequence_io import CROOT,TOPICS,FIELDS,derived_points,write_json,inside,schema

def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,default=CROOT/'outputs/v1b_continuous30');a=p.parse_args();run=inside(a.run);manifest=json.loads((run/'input_manifest.json').read_text());bagpath=run/'opdf_debug_ros1.bag'
 if bagpath.exists():raise FileExistsError('refusing to overwrite '+str(bagpath))
 summaries=[];index={'bag_path':str(bagpath.resolve()),'topics':TOPICS,'frames':[],'schema_path':str(run/'schema.json'),'no_control_topics':True};started=time.perf_counter();write_json(run/'schema.json',schema())
 try:
  with bagpath.open('xb')as handle:
   with rosbag.Bag(handle,'w',compression=rosbag.Compression.NONE)as bag:
    for entry in manifest['frames']:
     t=time.perf_counter();cache=Path(manifest['output_dir'])/entry['path'];serialized=cache.read_bytes()
     if hashlib.sha256(serialized).hexdigest()!=entry['sha256']:raise ValueError('raw cache sha differs from manifest')
     raw=PointCloud2();raw.deserialize(serialized);buffer=io.BytesIO();raw.serialize(buffer)
     if buffer.getvalue()!=serialized:raise ValueError('native ROS1 raw serialize changes original bytes')
     if raw.header.seq!=entry['seq']or raw.header.stamp.to_nsec()!=entry['header_stamp_ns']:raise ValueError('raw header differs from selected frame')
     with np.load(run/'frames'/f'{entry["key"]}.npz',allow_pickle=False)as z:
      keys=['xyz','intensity','labels','raw_slot_id','valid_xyz_mask','optical__optical_weak_score','optical__optical_available','geometry__scan_discontinuity_score','geometry__scan_available','geometry__spatial_diffuse_score','geometry__spatial_available'];arrays={k:z[k]for k in keys}
     read_ms=(time.perf_counter()-t)*1000;t=time.perf_counter();messages={TOPICS[0]:raw}
     for topic in TOPICS[1:]:
      points=derived_points(arrays,topic.rsplit('/',1)[1]);m=PointCloud2();m.header=Header(seq=raw.header.seq,stamp=raw.header.stamp,frame_id=raw.header.frame_id);m.height=1;m.width=len(points);m.fields=[PointField(**x)for x in FIELDS];m.is_bigendian=False;m.point_step=24;m.row_step=len(points)*24;m.data=points.tobytes();m.is_dense=True;messages[topic]=m
     build_ms=(time.perf_counter()-t)*1000;t=time.perf_counter();stamp=rospy.Time(entry['record_stamp_ns']//10**9,entry['record_stamp_ns']%10**9)
     for topic,message in messages.items():bag.write(topic,message,t=stamp)
     write_ms=(time.perf_counter()-t)*1000
     index['frames'].append({**{k:entry[k]for k in ('key','seq','header_stamp_ns','record_stamp_ns')},'frame_id':raw.header.frame_id,'topics':TOPICS,'points_by_topic':{t:m.width*m.height for t,m in messages.items()},'source_cache_path':str(cache.resolve()),'source_sha256':entry['sha256']})
     row={'key':entry['key'],'read_decode_ms':read_ms,'construct_messages_ms':build_ms,'bag_write_ms':write_ms,'messages':len(messages)};summaries.append(row);print(json.dumps(row),flush=True)
  write_json(run/'debug_frame_index.json',index);summary={'status':'COMPLETE','frames':len(index['frames']),'messages':sum(x['messages']for x in summaries),'bag_path':str(bagpath),'bag_bytes':bagpath.stat().st_size,'elapsed_seconds':time.perf_counter()-started,'per_frame_timings':summaries,'ros_nodes_started':False,'topics':TOPICS,'raw_whole_serialized_cache_roundtrip':True,'validation_status':'PENDING_INDEPENDENT_READBACK'};write_json(run/'ros1_export_summary.json',summary);print(json.dumps(summary),flush=True)
 except Exception as e:
  write_json(run/'ros1_export_failure.json',{'status':'FAILED','error':type(e).__name__+': '+str(e),'partial_bag_path':str(bagpath),'frames_written':len(index['frames']),'elapsed_seconds':time.perf_counter()-started});raise
if __name__=='__main__':main()
