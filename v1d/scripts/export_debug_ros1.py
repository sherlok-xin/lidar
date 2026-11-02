#!/usr/bin/env python3
"""Offline Noetic bag construction and complete native readback; never starts ROS."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
DROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(DROOT))
import os
os.environ.setdefault('TMPDIR',str(DROOT/'evidence/tmp'))
import argparse,hashlib,io,json,time
import numpy as np
from opdf_d.ros_layers import TOPICS,FIELDS,DTYPE,load_frame,filehash,schema


def inside(path):
    p=Path(path).resolve()
    try:p.relative_to(DROOT)
    except ValueError:raise ValueError('Every output must remain inside v1d')
    return p


def dump(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def serialize(message):
    b=io.BytesIO();message.serialize(b);return b.getvalue()


def check_raw_domain(raw,arrays):
    """Source NPZ coordinates and intensity must retain source 32-byte point bits."""
    if raw.is_bigendian or raw.point_step!=32 or raw.row_step!=raw.width*32:
        raise ValueError('Unsupported source layout; no implicit reinterpretation')
    fields=[(f.name,f.offset,f.datatype,f.count)for f in raw.fields]
    if fields!=[('x',0,7,1),('y',4,7,1),('z',8,7,1),('intensity',16,7,1)]:
        raise ValueError('Original source XYZI field schema changed')
    points=np.frombuffer(raw.data,dtype=np.dtype({'names':['x','y','z','intensity'],
        'formats':['<f4']*4,'offsets':[0,4,8,16],'itemsize':32}))
    slots=np.asarray(arrays['raw_slot_id'])
    if slots.shape!=(raw.height*raw.width,)or not np.array_equal(slots,np.arange(len(slots))):
        raise ValueError('Original full raw slot domain must remain exact, including invalid points')
    for column,key in enumerate(('x','y','z')):
        if points[key].tobytes()!=np.asarray(arrays['xyz'][:,column],dtype='<f4').tobytes():
            raise ValueError('Original coordinate bits differ: '+key)
    if points['intensity'].tobytes()!=np.asarray(arrays['intensity'],dtype='<f4').tobytes():
        raise ValueError('Original intensity bits differ')
    finite=np.column_stack([points[k]for k in ('x','y','z')]);finite=np.isfinite(finite).all(1)
    if not np.array_equal(finite,arrays['valid_xyz_mask']):raise ValueError('Source finite mask differs')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--mode',choices=['geometry_only','fusion'])
    p.add_argument('--output',type=Path,help='Default: selected run/mode; existing bag/index refused')
    p.add_argument('--seq',type=int,action='append',help='Bounded smoke subset; repeatable')
    p.add_argument('--c-aux-run',type=Path,default=DROOT.parent/'v1c/outputs/v1c_uniform_pair')
    p.add_argument('--guard-dir',type=Path)
    p.add_argument('--d1-source-run',type=Path)
    args=p.parse_args();run=args.run.resolve();selected=run/args.mode if args.mode else run
    out=inside(args.output or selected);out.mkdir(parents=True,exist_ok=True)
    bagpath=out/'opdf_debug_ros1.bag';indexpath=out/'debug_frame_index.json'
    for name in ('opdf_debug_ros1.bag','debug_frame_index.json','ros1_export_summary.json','schema.json','ros1_export_failure.json'):
        if (out/name).exists():raise FileExistsError('Refusing to overwrite '+str(out/name))
    # Native imports stay in main; host can test source binding without ROS installed.
    import rosbag,rospy
    from sensor_msgs.msg import PointCloud2,PointField
    from std_msgs.msg import Header
    manifestpath=selected/'input_manifest.json'
    if not manifestpath.exists():manifestpath=run/'input_manifest.json'
    manifest=json.loads(manifestpath.read_text());entries=manifest['frames']
    if args.seq:
        entries=[e for e in entries if e['seq']in args.seq]
        if set(e['seq']for e in entries)!=set(args.seq):raise ValueError('Requested seq absent')
    if not entries or len(set(e['seq']for e in entries))!=len(entries):raise ValueError('Empty/duplicate source identities')
    if any(not 245832<=e['seq']<=245861 for e in entries):raise ValueError('Only approved continuous30')
    index={'bag_path':str(bagpath),'topics':TOPICS,'frames':[],'schema_path':str(out/'schema.json'),
        'no_control_topics':True,'ros_nodes_started':False,'source_manifest':str(manifestpath),
        'logical_frame_group_not_network_atomic':True}
    dump(out/'export_execution.json',{'actual_argv':[sys.executable,*sys.argv],
        'source_files_sha256':{str(p):filehash(p)for p in (Path(__file__).resolve(),DROOT/'opdf_d/ros_layers.py',DROOT.parent/'v1c/opdf_c/sequence_io.py')},
        'source_manifest_sha256':filehash(manifestpath),'ros_nodes_started':False})
    spec=schema();spec['guard_requested']=args.guard_dir is not None
    dump(out/'schema.json',spec);expected={};timings=[];started=time.perf_counter()
    try:
        with bagpath.open('xb')as handle:
            with rosbag.Bag(handle,'w',compression=rosbag.Compression.NONE)as bag:
                for entry in entries:
                    t=time.perf_counter()
                    arrays,layers,provenance=load_frame(selected/'frames',entry,args.c_aux_run,args.guard_dir,args.d1_source_run)
                    cache=Path(manifest['output_dir'])/entry['path'];rawbytes=cache.read_bytes()
                    if hashlib.sha256(rawbytes).hexdigest()!=entry['sha256']:raise ValueError('Original raw cache SHA mismatch')
                    raw=PointCloud2();raw.deserialize(rawbytes)
                    if serialize(raw)!=rawbytes:raise ValueError('Native deserialize/serialize changes original raw bytes')
                    if raw.header.seq!=entry['seq']or raw.header.stamp.to_nsec()!=entry['header_stamp_ns']:
                        raise ValueError('Raw header mismatch')
                    check_raw_domain(raw,arrays);messages={TOPICS[0]:raw}
                    for topic,points in layers.items():
                        m=PointCloud2();m.header=Header(seq=raw.header.seq,stamp=raw.header.stamp,frame_id=raw.header.frame_id)
                        m.height=1;m.width=len(points);m.fields=[PointField(**x)for x in FIELDS]
                        m.is_bigendian=False;m.point_step=24;m.row_step=m.width*24;m.data=points.tobytes();m.is_dense=True
                        # Verify coordinate/I bits by original slot, independent of export masks.
                        slots=points['raw_slot_id'];valid=arrays['valid_xyz_mask'][slots]
                        if not valid.all()or len(np.unique(slots))!=len(slots):raise ValueError('Derived invalid/duplicate slots')
                        for col,key in enumerate(('x','y','z')):
                            if points[key].tobytes()!=np.asarray(arrays['xyz'][slots,col],dtype='<f4').tobytes():raise ValueError('Derived coordinate bits changed')
                        if points['intensity'].tobytes()!=np.asarray(arrays['intensity'][slots],dtype='<f4').tobytes():raise ValueError('Derived intensity bits changed')
                        messages[topic]=m
                    stamp=rospy.Time(entry['record_stamp_ns']//10**9,entry['record_stamp_ns']%10**9)
                    for topic in TOPICS:
                        m=messages[topic];payload=serialize(m);key=(entry['seq'],topic)
                        expected[key]={'sha256':hashlib.sha256(payload).hexdigest(),'bytes':len(payload),'points':m.width*m.height,
                                       'record_stamp_ns':entry['record_stamp_ns'],'header_stamp_ns':entry['header_stamp_ns'],'frame_id':raw.header.frame_id}
                        bag.write(topic,m,t=stamp)
                    row={k:entry[k]for k in ('key','seq','header_stamp_ns','record_stamp_ns')}
                    row.update(frame_id=raw.header.frame_id,topics=TOPICS,points_by_topic={topic:expected[(entry['seq'],topic)]['points']for topic in TOPICS},
                               source_cache_path=str(cache.resolve()),source_sha256=entry['sha256'],**provenance)
                    index['frames'].append(row)
                    timing={'seq':entry['seq'],'construct_and_write_ms':(time.perf_counter()-t)*1000}
                    timings.append(timing);print(json.dumps(timing),flush=True)
        # Read ALL messages with native Noetic; compare entire serialized payload hash.
        # This binds header, schemas, flags, coordinate/I/RGB bits and all slots together.
        seen=set();readback=[]
        with rosbag.Bag(str(bagpath),'r')as bag:
            if set(bag.get_type_and_topic_info().topics)!=set(TOPICS):raise ValueError('Bag topic allowlist differs')
            for topic,message,stamp in bag.read_messages():
                key=(message.header.seq,topic)
                if key not in expected or key in seen:raise ValueError('Unexpected/duplicate seq/topic')
                e=expected[key];payload=serialize(message)
                if message._type!='sensor_msgs/PointCloud2' or hashlib.sha256(payload).hexdigest()!=e['sha256']:
                    raise ValueError('Native readback payload/type differs')
                if stamp.to_nsec()!=e['record_stamp_ns']or message.header.stamp.to_nsec()!=e['header_stamp_ns']or message.header.frame_id!=e['frame_id']:
                    raise ValueError('Native readback dual time/frame differs')
                if topic!='/opdf_v1/raw':
                    fs=[dict(name=f.name,offset=f.offset,datatype=f.datatype,count=f.count)for f in message.fields]
                    if fs!=FIELDS or message.height!=1 or message.point_step!=24 or message.row_step!=24*message.width or message.is_bigendian or not message.is_dense:
                        raise ValueError('Native derived schema/stride/flags differs')
                    if len(np.frombuffer(message.data,dtype=DTYPE))!=e['points']:raise ValueError('Derived count differs')
                seen.add(key);readback.append(dict(seq=key[0],topic=topic,**e,status='PASS_EXACT_NATIVE_PAYLOAD'))
        if seen!=set(expected):raise ValueError('Missing native readback messages')
        dump(indexpath,index);dump(out/'ros1_native_readback.json',{'status':'PASS','messages':readback})
        summary={'status':'COMPLETE','frames':len(entries),'messages':len(seen),'topics':TOPICS,'bag_path':str(bagpath),
            'bag_bytes':bagpath.stat().st_size,'elapsed_seconds':time.perf_counter()-started,'native_readback':'ALL_MESSAGES_EXACT',
            'ros_nodes_started':False,'gui_tested':False,'per_frame_timings':timings,
            'guard_statuses':sorted(set(f['diagnostics']['guard_status']for f in index['frames'])),
            'candidate_clutter':sum(f['diagnostics']['candidate_clutter_count']for f in index['frames']),
            'suppressible':sum(f['diagnostics']['suppressible_count']for f in index['frames']),
            'deferred':sum(f['diagnostics']['deferred_count']for f in index['frames'])}
        dump(out/'ros1_export_summary.json',summary);print(json.dumps(summary),flush=True)
    except Exception as e:
        dump(out/'ros1_export_failure.json',{'status':'FAILED','error':type(e).__name__+': '+str(e),
            'frames_written':len(index['frames']),'partial_bag_path':str(bagpath),'elapsed_seconds':time.perf_counter()-started})
        raise


if __name__=='__main__':main()
