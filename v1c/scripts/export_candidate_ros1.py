#!/usr/bin/env python3
"""Copy frozen B debug messages and add review-only C layers, then read back all."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import argparse,copy,hashlib,io,json,time
import numpy as np
import rosbag,rospy
from sensor_msgs.msg import PointCloud2,PointField
from std_msgs.msg import Header
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
from opdf_c.sequence_io import FIELDS
EXTRA={'/opdf_v1/aerosol_suspect':('aerosol_suspect_mask',0x00FFE600),
       '/opdf_v1/entity_optical_conflict':('entity_optical_conflict_mask',0x00FFFFFF)}
DT=np.dtype({'names':['x','y','z','intensity','rgb','raw_slot_id'],
             'formats':['<f4','<f4','<f4','<f4','<u4','<u4'],'offsets':[0,4,8,12,16,20],'itemsize':24})
def sha_msg(m):
    b=io.BytesIO();m.serialize(b);return hashlib.sha256(b.getvalue()).hexdigest()
def dump(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def extra_message(arrays,key,rgb,source):
    mask=arrays[key].astype(bool);ids=arrays['raw_slot_id'][mask]
    if not np.all(arrays['valid_xyz_mask'][mask]&np.isfinite(arrays['xyz'][mask]).all(axis=1)):raise ValueError('Extra layer contains invalid points')
    if ids.size and ids.max()>np.iinfo(np.uint32).max:raise ValueError('Slot overflow')
    pts=np.zeros(len(ids),dtype=DT)
    for j,k in enumerate(('x','y','z')):pts[k]=arrays['xyz'][mask,j]
    pts['intensity']=arrays['intensity'][mask];pts['rgb']=rgb;pts['raw_slot_id']=ids
    m=PointCloud2();m.header=copy.deepcopy(source.header);m.height=1;m.width=len(pts)
    m.fields=[PointField(**f) for f in FIELDS];m.is_bigendian=False;m.point_step=24;m.row_step=24*len(pts);m.data=pts.tobytes();m.is_dense=True
    return m

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--candidate',type=Path,default=C/'outputs/v1c_uniform_pair');a=p.parse_args();run=a.candidate.resolve()
    try:run.relative_to(C)
    except ValueError:raise ValueError('Output must remain V1-C')
    bindex=json.loads((C/'outputs/v1b_continuous30/debug_frame_index.json').read_text());out=run/'opdf_debug_ros1.bag'
    if out.exists():raise FileExistsError('Refusing to overwrite existing candidate bag')
    index=copy.deepcopy(bindex);index['bag_path']=str(out);index['topics']=bindex['topics']+list(EXTRA)
    index['schema_path']=str(run/'schema.json');index['frames']=[];expected={};t0=time.perf_counter();timings=[]
    with rosbag.Bag(str(out),'w',compression=rosbag.Compression.NONE) as dest,rosbag.Bag(bindex['bag_path'],'r') as src:
        for row in bindex['frames']:
            ns=row['record_stamp_ns'];stamp=rospy.Time(ns//10**9,ns%10**9);end=rospy.Time((ns+1)//10**9,(ns+1)%10**9)
            t=time.perf_counter();messages={}
            for topic,m,record in src.read_messages(start_time=stamp,end_time=end):
                if record.to_nsec()!=ns:continue
                if topic not in bindex['topics'] or topic in messages:raise ValueError('Unexpected/duplicate source debug topic')
                messages[topic]=m;expected[(row['seq'],topic)]=sha_msg(m)
            if set(messages)!=set(bindex['topics']):raise ValueError('Missing baseline layer')
            with np.load(run/'frames'/(row['key']+'.npz'),allow_pickle=False) as z:arrays={k:z[k] for k in ['xyz','intensity','valid_xyz_mask','raw_slot_id','aerosol_suspect_mask','entity_optical_conflict_mask']}
            for topic,(key,rgb) in EXTRA.items():messages[topic]=extra_message(arrays,key,rgb,messages['/opdf_v1/raw'])
            for topic,m in messages.items():dest.write(topic,m,t=stamp)
            index['frames'].append(dict(row,topics=index['topics'],points_by_topic={t:m.width*m.height for t,m in messages.items()}))
            timings.append(dict(seq=row['seq'],read_build_write_ms=(time.perf_counter()-t)*1000))
    write_seconds=time.perf_counter()-t0;fail=[];seen=set();start=time.perf_counter();extra_counts={t:0 for t in EXTRA}
    rows={f['seq']:f for f in index['frames']}
    with rosbag.Bag(str(out),'r') as bag:
        for topic,m,record in bag.read_messages():
            row=rows.get(m.header.seq);key=(m.header.seq,topic)
            if row is None or topic not in index['topics'] or key in seen:raise ValueError('Unindexed/duplicate candidate debug message')
            seen.add(key)
            if record.to_nsec()!=row['record_stamp_ns'] or m.header.stamp.to_nsec()!=row['header_stamp_ns'] or m.header.frame_id!=row['frame_id']:raise ValueError('Candidate source timing/frame mismatch')
            if topic in bindex['topics']:
                if sha_msg(m)!=expected[key]:raise ValueError('Baseline cloud changed in candidate debug bag')
            else:
                maskkey,rgb=EXTRA[topic]
                if [(f.name,f.offset,f.datatype,f.count)for f in m.fields]!=[(f['name'],f['offset'],f['datatype'],f['count'])for f in FIELDS]:raise ValueError('Extra schema mismatch')
                if m.height!=1 or m.point_step!=24 or m.row_step!=24*m.width or m.is_bigendian or not m.is_dense:raise ValueError('Extra dimensions/flags mismatch')
                pts=np.frombuffer(m.data,dtype=DT)
                with np.load(run/'frames'/(row['key']+'.npz'),allow_pickle=False) as z:
                    mask=z[maskkey].astype(bool);ids=z['raw_slot_id'][mask]
                    if not np.array_equal(pts['raw_slot_id'],ids) or not np.all(pts['rgb']==rgb):raise ValueError('Extra slot or RGB mismatch')
                    for j,k in enumerate(('x','y','z')):
                        if pts[k].tobytes()!=z['xyz'][mask,j].astype('<f4').tobytes():raise ValueError('Extra XYZ mismatch')
                    if pts['intensity'].tobytes()!=z['intensity'][mask].astype('<f4').tobytes():raise ValueError('Extra intensity mismatch')
                extra_counts[topic]+=len(pts)
    if len(seen)!=len(index['frames'])*len(index['topics']):raise ValueError('Candidate bag message coverage missing')
    schema=json.loads((C/'outputs/v1b_continuous30/schema.json').read_text());schema['topics']=index['topics']
    schema['review_only_layers']={t:{'mask':k,'rgb_bits':hex(rgb),'never_authorizes_deletion':True}for t,(k,rgb) in EXTRA.items()}
    dump(run/'schema.json',schema);dump(run/'debug_frame_index.json',index)
    report=dict(status='PASS',frames=len(index['frames']),messages_validated=len(seen),bag_path=str(out),bag_bytes=out.stat().st_size,
                baseline_messages_byte_identical=len(expected),extra_counts=extra_counts,
                bag_read_build_write_seconds=write_seconds,readback_validation_seconds=time.perf_counter()-start,
                per_frame_timings=timings,failures=fail,ros_nodes_started=False,source='same original slot domain; additional diagnostic clouds contain existing echoes only')
    dump(run/'ros1_candidate_validation.json',report);print(json.dumps({k:v for k,v in report.items()if k!='per_frame_timings'}))

if __name__=='__main__':main()
