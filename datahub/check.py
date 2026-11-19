"""Read actual registered frames and test task masks against independent source bytes."""
import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .build import dump, jlines
from .reader import past_window, read_frame


def check(data, derived, bag_root=None):
    with (derived/"native_dataset_index.csv").open() as f:
        sequences=list(csv.DictReader(f))
    candidates={}
    found=Counter()
    uids=set()
    event_roles=defaultdict(set)
    all_rows=0
    for seq in sequences:
        if not seq["manifest_ref"]:
            continue
        rows=list(jlines(derived/seq["manifest_ref"]))
        assert len(rows)==int(seq["frames"])
        all_rows+=len(rows)
        for row in rows:
            assert row["uid"] not in uids
            uids.add(row["uid"])
            assert row["point_count_stored"]==row["stored_points"] and row["point_count_valid"]==row["valid_points"]
            assert row["header_stamp_ns"] is None or isinstance(row["header_stamp_ns"],str)
            if row["dataset_id"] in ("dustx","uchile"):
                event_roles[row["event_group"]].add(row["split"])
            if row["eligibility"]=="inventory_only":
                continue
            if row["dataset_id"]=="uchile":
                key=("uchile",row["temporal_tier"])
            elif row["dataset_id"]=="dustx":
                key=("dustx",row["sensor_id"])
            elif row["dataset_id"]=="smoke":
                key=("smoke",row["box_file_state"])
            else:
                key=("annotation",row["label_status"])
            candidates.setdefault(key,row)
            if row["dataset_id"]=="dustx" and row["sensor_id"]=="m1-p" and found["zero_intensity"]==0:
                raw=np.memmap(data/row["point_ref"],dtype="<f4",mode="r").reshape(-1,4)
                if np.all(raw[:,3]==0):
                    candidates[("dustx","intensity_all_zero")]=row
                    found["zero_intensity"]=1
        if len(rows)>=2:
            assert past_window(rows,0,2)==[]
            if rows[0]["temporal_tier"]=="STATIC_ORDER_ONLY" and rows[1]["frame_order"]==rows[0]["frame_order"]+1:
                assert len(past_window(rows,1,2))==2
                assert not past_window([dict(rows[0],split="other"),rows[1]],1,2)
                assert not past_window([dict(rows[0],sequence_id="other"),rows[1]],1,2)
                assert not past_window([dict(rows[0],frame_order=-20),rows[1]],1,2)
            if rows[0]["temporal_tier"]=="TEMPORAL_UNAVAILABLE":
                assert past_window(rows,1,2)==[]
    assert all(len(v)==1 for v in event_roles.values())
    evidence=[]
    if bag_root:
        for p in sorted(bag_root.glob("sequences/bag*/frames.jsonl")):
            row=next(jlines(p))
            candidates[("bag",row["sequence_id"])]=row
    for key,row in candidates.items():
        full=read_frame(row,data,False,bag_root)
        frame=read_frame(row,data,True,bag_root)
        mask=full["stored_valid_mask"]
        ids=frame["source_point_index"]
        np.testing.assert_array_equal(frame["xyz"],full["xyz"][mask])
        np.testing.assert_array_equal(ids,full["source_point_index"][mask])
        assert len(np.unique(ids))==len(ids) and np.isfinite(frame["xyz"]).all()
        assert not full["supervision_mask"][~mask].any()
        if row.get("valid_points") is not None:
            assert len(ids)==row["valid_points"]
        native=data/row["point_ref"]
        if key[0]=="uchile":
            np.testing.assert_array_equal(frame["xyz"],np.load(native)[ids])
            labels=np.load(data/row["label_ref"]).reshape(-1)
            np.testing.assert_array_equal(frame["task_label"],np.where(labels[ids]==0,2,1))
            assert row["header_stamp_ns"] is None
        elif key[0]=="dustx":
            arr=np.fromfile(native,dtype="<f4").reshape(-1,4)
            y=np.fromfile(data/row["label_ref"],dtype="u1")
            np.testing.assert_array_equal(frame["xyz"],arr[ids,:3])
            np.testing.assert_array_equal(frame["semantic_raw"],y[ids])
            if row["raw_label_schema"]=="dustx_fine":
                expected=np.ones(len(ids),"u1")
                expected[np.isin(y[ids],[0,10,11,25])]=0
                expected[y[ids]==9]=2
                np.testing.assert_array_equal(frame["task_label"],expected)
            else:
                assert not frame["supervision_mask"].any()
            if key[1]=="intensity_all_zero":
                assert np.all(arr[:,3]==0) and len(ids)>0 and frame["attribute_available"]["intensity"]["constant"]
            if row.get("exclude_zero_xyz"):
                assert not np.any(np.all(frame["xyz"]==0,axis=1))
        elif key[0]=="annotation":
            assert hashlib.sha256(full["source_point_index"].astype("<u4").tobytes()).hexdigest()==row["index_sha256"]
            assert int(ids.max())<row["source_cloud_points"] and not np.array_equal(ids,np.arange(len(ids)))
            expected_counts={int(k):v for k,v in row["raw_counts"].items() if v}
            assert dict(zip(*np.unique(full["semantic_raw"],return_counts=True)))==expected_counts
            assert not frame["supervision_mask"][np.isin(frame["semantic_raw"],[0,4])].any()
        else:
            assert frame["semantic_raw"] is None and not frame["supervision_mask"].any()
            if key[0]=="smoke":
                assert (frame["boxes"] is None)==(row["box_file_state"]=="missing")
            if key[0]=="bag":
                with np.load(bag_root/row["point_ref"]) as z:
                    np.testing.assert_array_equal(ids,z["source_point_index"][z["valid_mask"]])
        evidence.append(dict(dataset=key[0],stratum=key[1],uid=row["uid"],split=row["split"],
                             stored=len(mask),valid=len(ids),ignored=int((~frame["supervision_mask"]).sum()),
                             source_index_max=int(ids.max()) if len(ids) else None))
    assert {k[0] for k in candidates}>={"uchile","dustx","smoke","annotation"}
    return dict(status="PASS",native_frames_indexed=all_rows,split_groups_checked=len(event_roles),samples=evidence)


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--bag-root",type=Path)
    ap.add_argument("--report",type=Path)
    args=ap.parse_args()
    result=check(Path(os.environ["DATA_ROOT"]),Path(os.environ["DERIVED_ROOT"]),args.bag_root)
    if args.report:
        dump(args.report,result)
    print(json.dumps({k:v if k!="samples" else len(v) for k,v in result.items()}))
