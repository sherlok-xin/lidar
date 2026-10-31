#!/usr/bin/env python3
"""Bounded ROS2 debug-only publisher; source Humble before running.

Only /opdf_v1/{raw,solid,aerosol_candidate,unknown,ground}. No TF/control.
--selfcheck serializes/deserializes messages without creating a ROS node.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('ROS_LOG_DIR', str(ROOT/'evidence/ros_logs'))
import numpy as np
from opdf.visualization import load_result

TOPICS = ('/opdf_v1/raw','/opdf_v1/solid','/opdf_v1/aerosol_candidate',
          '/opdf_v1/unknown','/opdf_v1/ground')


def guard_domain(domain_id):
    if not 50 <= domain_id <= 232:
        raise ValueError('Use an explicit isolated debug domain 50..232, never default 0')
    if os.environ.get('ROS_LOCALHOST_ONLY') != '1':
        raise ValueError('Set ROS_LOCALHOST_ONLY=1 explicitly before running')
    if os.environ.get('ROS_DOMAIN_ID') != str(domain_id):
        raise ValueError('ROS_DOMAIN_ID must explicitly match --domain-id')


def messages_for_result(npz_path):
    from sensor_msgs.msg import PointCloud2, PointField
    from std_msgs.msg import Header
    a = load_result(npz_path)
    side = json.loads(Path(npz_path).with_suffix('.json').read_text())
    meta = side.get('metadata', side)
    stamp = meta.get('header_stamp_ns')
    frame_id = meta.get('frame_id')
    if not isinstance(stamp, int) or stamp <= 0 or not isinstance(frame_id, str) or not frame_id:
        raise ValueError('Original nonempty frame and integer header stamp are required')
    header = Header(); header.frame_id=frame_id
    header.stamp.sec=stamp//1_000_000_000; header.stamp.nanosec=stamp%1_000_000_000
    finite = np.isfinite(a['xyz']).all(axis=1) & a['valid_xyz_mask'].astype(bool)

    def compact(mask):
        slots = a['raw_slot_id'][mask]
        if np.any(slots > np.iinfo(np.uint32).max):
            raise ValueError('PointField raw_slot_id uint32 capacity exceeded')
        dt = np.dtype({'names':['x','y','z','intensity','raw_slot_id'],
                       'formats':['<f4','<f4','<f4','<f4','<u4'],
                       'offsets':[0,4,8,12,16], 'itemsize':20})
        points=np.zeros(int(mask.sum()),dtype=dt)
        for i,name in enumerate(('x','y','z')):points[name]=a['xyz'][mask,i]
        points['intensity']=a['intensity'][mask]; points['raw_slot_id']=slots
        msg=PointCloud2();msg.header=header;msg.height=1;msg.width=len(points)
        msg.fields=[PointField(name=name,offset=offset,datatype=datatype,count=1)
                    for name,offset,datatype in [('x',0,7),('y',4,7),('z',8,7),('intensity',12,7),('raw_slot_id',16,6)]]
        msg.is_bigendian=False;msg.point_step=20;msg.row_step=20*len(points)
        msg.data=points.tobytes();msg.is_dense=True
        return msg

    # RAW preserves source PointCloud2 organization, fields and exact point bytes
    # if the cached source is available; no bag is opened by this script.
    cache = meta.get('source_cache_path')
    raw_mode='compact_finite_npz_raw'
    if cache:
        from opdf.io_rosbag import load_cached_frame
        frame=load_cached_frame(cache)
        if frame.metadata().get('raw_message_sha256') != meta.get('raw_message_sha256'):
            raise ValueError('Raw cache identity differs from result metadata')
        raw=PointCloud2();raw.header=header;raw.height=frame.height;raw.width=frame.width
        raw.fields=[PointField(name=f['name'],offset=f['offset'],datatype=f['datatype'],count=f['count']) for f in frame.field_schema]
        raw.is_bigendian=frame.is_bigendian;raw.point_step=frame.point_step;raw.row_step=frame.row_step
        raw.data=frame.raw_data;raw.is_dense=frame.is_dense;raw_mode='exact_cached_source_point_bytes'
    else:
        raw=compact(finite)
    labels=a['labels']
    masks=(finite & np.isin(labels,[1,3]), finite & (labels==2), finite & (labels==3), finite & (labels==4))
    messages=[raw]+[compact(mask) for mask in masks]
    return dict(zip(TOPICS,messages)), dict(raw_mode=raw_mode, original_frame_id=frame_id,
             original_header_stamp_ns=stamp, no_gt=True,
             counts={topic:int(msg.width*msg.height) for topic,msg in zip(TOPICS,messages)},
             solid_definition='E+U protected; UNKNOWN intentionally also has a separate debug topic')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('npz');p.add_argument('--domain-id',type=int,required=True)
    p.add_argument('--selfcheck',action='store_true');p.add_argument('--self-receive',action='store_true')
    p.add_argument('--repeat',type=int,default=3);p.add_argument('--rate',type=float,default=1.)
    p.add_argument('--log',help='Optional JSON evidence, under opdf_v1 only')
    a=p.parse_args();guard_domain(a.domain_id)
    ros_log_dir=Path(os.environ['ROS_LOG_DIR']).resolve()
    if not ros_log_dir.is_relative_to(ROOT):
        p.error('ROS_LOG_DIR must remain under opdf_v1')
    ros_log_dir.mkdir(parents=True,exist_ok=True)
    if not 1<=a.repeat<=30 or not 0<a.rate<=10:
        p.error('bounded repeat must be 1..30 and rate in (0,10]')
    if a.log and not Path(a.log).resolve().is_relative_to(ROOT):
        p.error('log must remain under opdf_v1')
    from rclpy.serialization import serialize_message, deserialize_message
    from sensor_msgs.msg import PointCloud2
    messages,report=messages_for_result(a.npz)
    report.update(domain_id=a.domain_id,localhost_only=True,rviz_gui_verified=False,ros_node_created=False)
    for topic,msg in messages.items():
        restored=deserialize_message(serialize_message(msg),PointCloud2)
        if bytes(restored.data)!=bytes(msg.data) or restored.header!=msg.header:
            raise ValueError(f'Serialization roundtrip mismatch: {topic}')
    report['cdr_roundtrip']='PASS'
    if not a.selfcheck:
        import rclpy
        from rclpy.qos import qos_profile_sensor_data
        rclpy.init(args=[]);node=rclpy.create_node('opdf_v1_debug_preview')
        report['ros_node_created']=True
        pubs={topic:node.create_publisher(PointCloud2,topic,qos_profile_sensor_data) for topic in TOPICS}
        received={topic:0 for topic in TOPICS}; failures=[]; subs=[]
        def on_message(topic,msg):
            expected=messages[topic]
            if msg.header!=expected.header or bytes(msg.data)!=bytes(expected.data):
                failures.append(topic)
            received[topic]+=1
        if a.self_receive:
            for topic in TOPICS:
                subs.append(node.create_subscription(PointCloud2,topic,lambda msg,t=topic:on_message(t,msg),qos_profile_sensor_data))
        try:
            end=time.monotonic()+1.
            while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.05)
            for _ in range(a.repeat):
                for topic,msg in messages.items():pubs[topic].publish(msg)
                end=time.monotonic()+1/a.rate
                while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.05)
            report.update(received=received,receive_mismatches=failures,published_repetitions=a.repeat,
                          dds_self_receive='PASS' if a.self_receive and all(received.values()) and not failures else 'NOT_REQUESTED' if not a.self_receive else 'FAIL')
        finally:
            node.destroy_node();rclpy.shutdown()
        if a.self_receive and report['dds_self_receive']!='PASS':
            report['error']='Debug DDS self-receive did not pass; RViz not verified'
    if a.log:Path(a.log).parent.mkdir(parents=True,exist_ok=True);Path(a.log).write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    if report.get('dds_self_receive')=='FAIL':raise SystemExit(2)


if __name__=='__main__':main()
