import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

from ros1_window import Bag, PC2, SCAN, PACKET, ns, pcd, pointcloud, scan, sha

SCHEMA="lidar-hub/bag-window-v1"
POINT=np.dtype([("x","<f4"),("y","<f4"),("z","<f4"),("intensity","u1"),("ring","<u2"),("timestamp","<f8")])


def store_json(path,value):
    with path.open("x") as handle:json.dump(value,handle,ensure_ascii=False,indent=2,allow_nan=False)


class Ruby:
    def __init__(self,lib):
        self.lib=ctypes.CDLL(str(Path(lib).resolve()))
        self.lib.ruby_create.restype=ctypes.c_void_p
        self.lib.ruby_destroy.argtypes=[ctypes.c_void_p]
        self.lib.ruby_difop.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_uint]
        self.lib.ruby_packet.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint]
        self.lib.ruby_split_notifications.argtypes=[ctypes.c_void_p]
        self.state=self.lib.ruby_create()
        if not self.state:raise RuntimeError("cannot initialize rs_driver")
        self.info=None

    def close(self):self.lib.ruby_destroy(self.state)

    def calibration(self,data):
        if len(data)!=1248 or data[:8]!=bytes.fromhex("a5ff005a11115555") or data[-2:]!=bytes.fromhex("0ff0"):
            raise ValueError("DIFOP signature/length/trailer mismatch")
        angles={}
        for axis in ("vertical","horizontal"):
            pos=getattr(self.lib,"ruby_"+axis+"_offset")()
            packed=np.frombuffer(data,np.uint8,count=384,offset=pos).reshape(128,3).astype(int)
            if not np.isin(packed[:,0],[0,1]).all():raise ValueError("invalid sign in DIFOP angle")
            signed=np.where(packed[:,0]==0,1,-1)*(packed[:,1]*256+packed[:,2])
            angles[axis]=signed
        if len(np.unique(angles["vertical"]))<100 or max(abs(angles["vertical"]))>=9000:
            raise ValueError("no plausible live 128-channel vertical calibration")
        if self.lib.ruby_difop(self.state,data,len(data))!=0:raise RuntimeError("driver rejected DIFOP calibration")
        self.info=dict(sha256=sha(data),angle_unit="0.01 degree per driver layout",
                       return_mode_byte=int(data[self.lib.ruby_mode_offset()]),
                       vertical_distinct=int(len(np.unique(angles["vertical"]))),
                       vertical_range=angles["vertical"][[np.argmin(angles["vertical"]),np.argmax(angles["vertical"])]].tolist(),
                       horizontal_range=[int(angles["horizontal"].min()),int(angles["horizontal"].max())])
        return self.info

    def cloud(self,data):
        seq,header,frame,packets=scan(data);per=384
        cloud=np.empty(len(packets)*per,POINT)
        stamps=[];device_us=[];raw_dist=[];raw_i=[];ids=set();block_return=[]
        splits=self.lib.ruby_split_notifications(self.state)
        for pos,(stamp,payload) in enumerate(packets):
            if payload[:6]!=bytes.fromhex("55aa055a0001") or payload[self.lib.ruby_family_offset()]!=4:
                raise ValueError("RS-Ruby protocol or family byte not verified")
            view=cloud[pos*per:(pos+1)*per]
            if self.lib.ruby_packet(self.state,payload,len(payload),view.ctypes.data,view.nbytes)!=0:
                raise ValueError("driver rejected block geometry")
            stamps.append(stamp);device_us.append(int.from_bytes(payload[10:16],"big")*1000000+int.from_bytes(payload[16:20],"big"))
            ids.add((payload[30],payload[31]))
            for block in (80,468,856):
                channel=np.frombuffer(payload,dtype=np.dtype([("d",">u2"),("i","u1")]),count=128,offset=block+4)
                raw_dist.append(channel["d"]);raw_i.append(channel["i"]);block_return.append(payload[block+1])
        xyz=np.column_stack([cloud[axis] for axis in "xyz"])
        valid=np.isfinite(xyz).all(1)&(xyz!=0).any(1)
        raw_dist=np.concatenate(raw_dist);raw_i=np.concatenate(raw_i)
        expected=raw_dist.astype(np.float64)*.005
        residual=abs(np.linalg.norm(xyz[valid],axis=1)-expected[valid])
        if not valid.any() or np.max(residual)>.039 or not np.array_equal(cloud["intensity"][valid],raw_i[valid]):
            raise ValueError("decoded geometry/intensity disagrees with native channels")
        if not (np.sort(cloud["ring"].reshape(-1,128),axis=1)==np.arange(128)).all():
            raise ValueError("decoded ring is not a calibrated per-block permutation")
        if not np.isfinite(cloud["timestamp"]).all():raise ValueError("driver returned nonfinite point timing")
        arrays=dict(xyz=xyz,intensity=cloud["intensity"],source_point_index=np.arange(len(cloud),dtype=np.uint32),
            valid_mask=valid,ring=cloud["ring"],driver_timestamp_seconds=cloud["timestamp"],
            packet_envelope_stamp_ns=np.array(stamps,dtype=np.uint64),msop_device_time_us=np.array(device_us,dtype=np.uint64),
            raw_distance_counts=raw_dist,raw_intensity=raw_i,raw_block_return_byte=np.array(block_return,np.uint8),
            serialized_message=np.frombuffer(data,dtype=np.uint8))
        meta=dict(seq=seq,header_stamp_ns=str(header),source_frame_id=frame,coordinate_frame="rs_ruby_native",
            grouping="one native ROS scan envelope in stored packet order; not resplit at inferred turn boundary",
            driver_split_notifications=self.lib.ruby_split_notifications(self.state)-splits,packet_count=len(packets),
            blocks_per_packet=3,channels_per_block=128,intensity_available=True,family_model_bytes=sorted(ids),
            packet_envelope_zero_count=stamps.count(0),device_us_first=str(device_us[0]),device_us_last=str(device_us[-1]),
            driver_stamp_first_seconds=float(cloud["timestamp"][0]),driver_stamp_last_seconds=float(cloud["timestamp"][-1]),
            xyz_min=np.min(xyz[valid],axis=0).tolist(),xyz_max=np.max(xyz[valid],axis=0).tolist(),
            max_abs_range_residual_m=float(residual.max()),wire_sha256=sha(data))
        return arrays,meta


def extract(data_root,derived,relative,topic,kind,take,start,driver=None,driver_commit=None,event=None):
    if not 1<=take<=100 or start<0:raise ValueError("bounded frame count 1..100 required")
    data_root=Path(data_root).resolve();derived=Path(derived).resolve()
    path=(data_root/relative).resolve()
    if data_root not in path.parents or data_root==derived or data_root in derived.parents:
        raise ValueError("input/output root guard")
    timer=time.perf_counter()
    with Bag(path) as bag:
        cname,ctype=("sensor_msgs/PointCloud2",PC2) if kind=="pc2" else ("rslidar_msgs/rslidarScan",SCAN)
        cid=bag.topic(topic,cname,ctype)
        did=bag.topic(topic+"_difop","rslidar_msgs/rslidarPacket",PACKET) if kind=="ruby" else None
        seq_id="bag_"+kind+"_"+sha((bag.identity+"|"+topic).encode())[:20]
        group=event or "unknown:"+bag.identity[:20]
        target=derived/"sequences"/seq_id;target.mkdir(parents=True,exist_ok=False)
        points=target/"sensor_data"/"lidar1";points.mkdir(parents=True)
        preview=target/"derived";preview.mkdir()
        engine=Ruby(driver) if kind=="ruby" else None
        records=[];calibrations=[];seen=set();last=None
        try:
            cids={cid} if did is None else {cid,did}
            for key,ordinal,record_time,loc,msg in bag.messages(cids,start if did is None else 0):
                if key==did:
                    if len(msg)!=1256:raise ValueError("incompatible DIFOP envelope")
                    info=engine.calibration(msg[8:])
                    caldir=target/"sensor_data"/"calibration";caldir.mkdir(exist_ok=True)
                    cal=caldir/("difop_%d.bin"%ordinal);cal.write_bytes(msg)
                    calibrations.append(dict(info,source_message_ordinal=ordinal,locator=loc,record_stamp_ns=str(record_time),
                        envelope_stamp_ns=str(ns(msg[:8])),source_ref=str(cal.relative_to(derived))))
                    continue
                if ordinal<start or (engine and not calibrations):continue
                if engine and record_time<int(calibrations[-1]["record_stamp_ns"]):continue
                arrays,meta=pointcloud(msg) if engine is None else engine.cloud(msg)
                if records and ordinal!=records[-1]["source_message_ordinal"]+1:raise ValueError("nonconsecutive source scan ordinals")
                stamp=int(meta["header_stamp_ns"]);uid=sha((bag.identity+"|"+topic+"|"+str(ordinal)).encode())
                target_npz=points/(uid+".npz")
                np.savez_compressed(target_npz,**arrays)
                if len(records)==0:pcd(preview/(uid+".pcd"),arrays)
                timing=("ZERO" if stamp==0 else "DUPLICATE_IN_WINDOW" if stamp in seen else "REGRESSED_IN_WINDOW" if last is not None and stamp<last else "SOURCE_HEADER_UNSYNCHRONIZED")
                seen.add(stamp);last=stamp
                rec=dict(uid=uid,frame_uid=uid,dataset_id="rosbag",sequence_id=seq_id,event_group=group,event_group_id=group,
                    sensor_id="lidar1",frame_order=len(records),format="bag_npz",schema_version=SCHEMA,
                    source_ref=str(path.relative_to(data_root)),source_topic=topic,source_message_ordinal=ordinal,
                    source_record_locator=loc,point_ref_root="derived",point_ref=str(target_npz.relative_to(derived)),
                    label_ref=None,raw_label_schema="none",label_status="UNLABELED",label_version=None,medium="unknown",
                    stamp_ns=str(stamp),header_stamp_ns=str(stamp),bag_record_stamp_ns=str(record_time),timestamp_source="ROS1 scan header; bag record separately preserved",
                    clock_status=timing,coordinate_frame=meta["coordinate_frame"],geometry_domain="RAW_POINTCLOUD2" if engine is None else "RS128_NATIVE_DRIVER",
                    pose_status="UNAVAILABLE_NOT_JOINED",calibration_status="NOT_VERIFIED" if not engine else "PACKET_INTRINSICS_ONLY",
                    stored_points=len(arrays["xyz"]),point_count_stored=len(arrays["xyz"]),valid_points=int(arrays["valid_mask"].sum()),
                    point_count_valid=int(arrays["valid_mask"].sum()),source_point_index_domain="row-major PointCloud2 slot; byte=row*row_step+column*point_step" if not engine else "scan packet ordinal*384 + MSOP block*128 + hardware channel (not sorted ring)",
                    split="UNASSIGNED_UNLABELED",details=meta)
                if engine:rec["calibration_ref"]=calibrations[-1]["source_ref"]
                records.append(rec)
                if len(records)==take:break
        finally:
            if engine:engine.close()
        if len(records)!=take:raise ValueError("short bounded window; no complete sequence manifest issued")
        with (target/"frames.jsonl").open("x") as f:
            for rec in records:f.write(json.dumps(rec,ensure_ascii=False,allow_nan=False)+"\n")
        summary=dict(dataset_id="rosbag",sequence_id=seq_id,event_group=group,event_group_id=group,format="bag_npz",
                     source_ref=str(path.relative_to(data_root)),source_topic=topic,source_md5=ctype,source_datatype=cname,
                     source_identity=bag.identity,identity_scope="first64KiB,size,footer offset; not full integrity hash",
                     format_version=SCHEMA,frames=len(records),stored_points=sum(r["stored_points"] for r in records),
                     valid_points=sum(r["valid_points"] for r in records),label_source="UNLABELED",split="UNASSIGNED_UNLABELED",
                     temporal_tier="ORDER_ONLY_NO_VERIFIED_POSE",eligibility="UNLABELED_BOUNDED_EXTRACTION",
                     ordinal_range=[records[0]["source_message_ordinal"],records[-1]["source_message_ordinal"]],
                     bytes_read=bag.bytes,seconds=time.perf_counter()-timer,calibrations=calibrations,
                     point_validity="finite XYZ excluding exact zero-vector placeholders, never intensity threshold",
                     driver_commit=driver_commit,driver_binary_sha256=sha(Path(driver).read_bytes()) if driver else None,
                     driver_config={"model":"RS-Ruby/RS128","clock":"original MSOP sensor clock, absolute basis unverified","dense_points":False,"use_lidar_clock":True,"wait_for_difop":True,"min_distance_m":.4,"max_distance_m":250} if driver else None)
        store_json(target/"sequence.json",summary)
        print(json.dumps(summary,ensure_ascii=False));return summary


if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("--data-root",default=os.environ.get("DATA_ROOT"));cli.add_argument("--derived-root",default=os.environ.get("DERIVED_ROOT"))
    cli.add_argument("--source",required=True);cli.add_argument("--topic",required=True);cli.add_argument("--kind",choices=["pc2","ruby"],required=True)
    cli.add_argument("--take",type=int,default=3);cli.add_argument("--start",type=int,default=0);cli.add_argument("--driver");cli.add_argument("--driver-commit");cli.add_argument("--event-group")
    opts=cli.parse_args()
    if not opts.data_root or not opts.derived_root or (opts.kind=="ruby" and (not opts.driver or not opts.driver_commit)):
        cli.error("data/derived roots required; raw packets also require verified rs_driver bridge and revision")
    extract(opts.data_root,opts.derived_root,opts.source,opts.topic,opts.kind,opts.take,opts.start,opts.driver,opts.driver_commit,opts.event_group)
