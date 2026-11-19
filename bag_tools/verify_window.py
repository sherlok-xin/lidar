"""Independently check raw source bytes, array identity, calibrated Z and binary PCD."""
import argparse
import json
import struct
from pathlib import Path

import numpy as np
from ros1_window import Bag, TYPES, sha


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def ros_header(data):
    seq, sec, subsec, length = struct.unpack_from("<IIII",data)
    require(subsec < 1_000_000_000, "invalid header subsecond")
    return seq, sec*1_000_000_000+subsec, data[16:16+length].decode(), 16+length


def verify_pc2(wire, cache, detail):
    _, _, _, pos = ros_header(wire)
    h,w,fields = struct.unpack_from("<III",wire,pos)
    pos += 12
    require((h,w,fields)==(detail["height"],detail["width"],len(detail["fields"])),"shape/schema mismatch")
    descriptors = []
    for declared in detail["fields"]:
        length, = struct.unpack_from("<I",wire,pos)
        pos += 4
        name = wire[pos:pos+length].decode()
        pos += length
        offset,kind,count = struct.unpack_from("<IBI",wire,pos)
        pos += 9
        require((name,offset,kind,count)==tuple(declared[k] for k in ("name","offset","datatype","count")),
                "source PointField mismatch")
        descriptors.append((declared,offset,kind,count))
    endian,step,stride,size = struct.unpack_from("<BIII",wire,pos)
    pos += 13
    require((bool(endian),step,stride,size)==(detail["is_bigendian"],detail["point_step"],detail["row_step"],h*detail["row_step"]),
            "source stride mismatch")
    source_cols = {}
    for declared,off,kind,count in descriptors:
        dtype = np.dtype((">" if endian else "<")+TYPES[kind])
        values = np.ndarray((h,w,count),dtype,buffer=wire,offset=pos+off,strides=(stride,step,dtype.itemsize))
        values = values.reshape(-1,count)
        if count==1: values = values[:,0]
        require(np.array_equal(cache[declared["key"]],values,equal_nan=True), "serialized PointField does not match cache")
        source_cols[declared["name"]] = values
    require(np.array_equal(np.column_stack([source_cols[k] for k in "xyz"]),cache["xyz"],equal_nan=True),"geometry differs")
    if "intensity" in source_cols:
        require(np.array_equal(source_cols["intensity"],cache["intensity"],equal_nan=True),"intensity differs")
    return {"all_declared_fields_verified":len(descriptors),"nonpoint_bytes_preserved_in_wire":True}


def verify_packets(wire, cal, cache):
    _, header_stamp, _, pos = ros_header(wire)
    count, = struct.unpack_from("<I",wire,pos)
    pk = np.frombuffer(wire,np.uint8,offset=pos+4).reshape(count,1256)
    # Offsets are taken from the RS128 MSOP/DIFOP packet structures of the frozen driver.
    channels=np.stack([pk[:,8+o+4:8+o+388].reshape(count,128,3) for o in (80,468,856)],axis=1).reshape(-1,3)
    require(np.all(pk[:,8+30]==4) and np.all(pk[:,8+np.array([80,468,856])]==254),"unsupported native block")
    envelope=pk[:,:8].copy().view("<u4").reshape(-1,2).astype(np.uint64)
    envelope_ns=envelope[:,0]*1_000_000_000+envelope[:,1]
    require(np.array_equal(envelope_ns,cache["packet_envelope_stamp_ns"]),"packet clock missing/corrupted")
    raw_counts=channels[:,0].astype(int)*256+channels[:,1]
    intensity=channels[:,2]
    require(np.array_equal(raw_counts,cache["raw_distance_counts"]) and np.array_equal(intensity,cache["raw_intensity"]),
            "hardware channel/source index mismatch")
    valid=cache["valid_mask"]
    distance=raw_counts[valid]*0.005
    require(np.array_equal(valid,(raw_counts*.005>=.4)&(raw_counts*.005<=250)),"driver validity differs from source range gate")
    require(np.array_equal(intensity[valid],cache["intensity"][valid]),"native intensity differs")
    xyz=cache["xyz"][valid]
    vertical=np.frombuffer(cal,np.uint8,count=384,offset=8+468).reshape(128,3).astype(int)
    vertical=np.where(vertical[:,0]==0,1,-1)*(vertical[:,1]*256+vertical[:,2])
    ring=np.argsort(np.argsort(vertical))
    channel=np.arange(len(raw_counts))%128
    require(np.array_equal(ring[channel],cache["ring"]),"calibrated ring/source channel permutation differs")
    delta_z=abs(distance*np.sin(np.deg2rad(vertical[channel[valid]]*.01))-xyz[:,2])
    delta_range=abs(np.linalg.norm(xyz,axis=1)-distance)
    require(delta_z.max()<.0001 and delta_range.max()<.039,"calibration geometry validation failed")
    us=int.from_bytes(pk[0,8+10:8+16],"big")*1_000_000+int.from_bytes(pk[0,8+16:8+20],"big")
    offset=us*1000-header_stamp
    return dict(verified_hardware_channels=int(len(raw_counts)),max_absolute_calibrated_z_error_m=float(delta_z.max()),
                max_absolute_range_difference_m=float(delta_range.max()),
                device_first_us_minus_ros_header_ns=str(offset),zero_envelope_stamps=int((envelope_ns==0).sum()))


def verify_pcd(path,cache):
    data=path.read_bytes()
    header,sep,body=data.partition(b"DATA binary\n")
    require(sep and b"FIELDS x y z intensity source_point_index\n" in header,"binary PCD schema differs")
    table=np.frombuffer(body,np.dtype([("xyz","<f4",(3,)),("i","<f4"),("idx","<u4")]))
    mask=cache["valid_mask"]
    require(np.array_equal(table["idx"],cache["source_point_index"][mask]),"PCD indices differ")
    require(np.array_equal(table["xyz"],cache["xyz"][mask]) and np.array_equal(table["i"],cache["intensity"][mask],equal_nan=True),
            "PCD preview values differ")
    return len(table)


def verify(data,derived):
    checks=[]
    for path in sorted((derived/"sequences").glob("bag_*/sequence.json")):
        seq=json.loads(path.read_text())
        rows=[json.loads(s) for s in (path.parent/"frames.jsonl").read_text().splitlines()]
        require(len(rows)==seq["frames"],"frame count mismatch")
        first=rows[0]["source_message_ordinal"]
        with Bag(data/seq["source_ref"]) as bag:
            ids=bag.topic(seq["source_topic"],seq["source_datatype"],seq["source_md5"])
            require(bag.identity==seq["source_identity"],"source identity mismatch")
            messages=bag.messages({ids},first)
            for i,r in enumerate(rows):
                _,ordinal,record,loc,wire=next(messages)
                require(ordinal==r["source_message_ordinal"]==first+i and loc==r["source_record_locator"],"ordinal/locator mismatch")
                require(str(record)==r["bag_record_stamp_ns"] and str(ros_header(wire)[1])==r["header_stamp_ns"],"source time mismatch")
                require(sha(wire)==r["details"]["wire_sha256"],"wire hash mismatch")
                with np.load(derived/r["point_ref"],allow_pickle=False) as cache:
                    require(wire==cache["serialized_message"].tobytes(),"wire cache mismatch")
                    slots=cache["source_point_index"]
                    require(np.array_equal(slots,np.arange(len(slots))) and slots.dtype.kind=="u","original slot mismatch")
                    xyz=cache["xyz"]
                    mask=np.isfinite(xyz).all(1)&np.any(xyz!=0,axis=1)
                    require(np.array_equal(mask,cache["valid_mask"]) and int(mask.sum())==r["valid_points"],"validity mismatch")
                    if "calibration_ref" in r:
                        geometry=verify_packets(wire,(derived/r["calibration_ref"]).read_bytes(),cache)
                    else:
                        geometry=verify_pc2(wire,cache,r["details"])
                    case=dict(uid=r["uid"],sequence_id=seq["sequence_id"],source_message_ordinal=ordinal,
                              header_stamp_ns=r["header_stamp_ns"],record_stamp_ns=r["bag_record_stamp_ns"],
                              stored=len(slots),valid=int(mask.sum()),zero_intensity_valid=int((mask&(cache["intensity"]==0)).sum()),
                              geometry_checks=geometry)
                    if i==0:
                        case["pcd_points_checked"]=verify_pcd(path.parent/"derived"/(r["uid"]+".pcd"),cache)
                    checks.append(case)
    require(checks,"missing derived windows")
    receipt={"status":"PASS","frames_checked":len(checks),"frames":checks}
    with (derived/"reports"/"bag_window_qa.json").open("x") as out:
        json.dump(receipt,out,indent=2)
    print(json.dumps({"status":"PASS","frames":len(checks),"source_slots":sum(c["stored"] for c in checks)}))


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root",type=Path,required=True)
    ap.add_argument("--derived-root",type=Path,required=True)
    opt=ap.parse_args()
    verify(opt.data_root,opt.derived_root)
