"""Independently verify the private arrays and save a small, payload-free receipt."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image


def read(path):
    return json.loads(path.read_text())


def main():
    cli=argparse.ArgumentParser()
    for name in ("case","first","second","rviz","out"):
        cli.add_argument("--"+name,type=Path,required=True)
    args=cli.parse_args()
    meta=read(args.case/"review.json")
    if meta["split"]!="train" or meta["source_ref"]!="interior1/Area_1/amtc_068":
        raise ValueError("unexpected sample")
    with np.load(args.case/"sample.npz",allow_pickle=False) as sample:
        source=np.arange(len(sample["xyz"]),dtype=np.uint32)
        np.testing.assert_array_equal(source,sample["source_point_index"])
        valid=sample["valid"];ref=sample["semantic_raw"];label=sample["task_label"]
        np.testing.assert_array_equal(valid,np.isfinite(sample["xyz"]).all(1))
        np.testing.assert_array_equal(label[valid],np.where(ref[valid]==0,2,1))
        expected={"raw":len(source),"valid":int(valid.sum()),"index":int(valid.sum()),
                  "reference":int((valid & (label!=0)).sum()),"ignored":int((valid & (label==0)).sum())}
    with np.load(args.first/"prediction.npz",allow_pickle=False) as frozen,np.load(args.second/"prediction.npz",allow_pickle=False) as portable:
        if set(frozen.files)!=set(portable.files):raise ValueError("different forward schema")
        for name in frozen:
            np.testing.assert_array_equal(frozen[name],portable[name])
        np.testing.assert_array_equal(source,frozen["source_point_index"])
        np.testing.assert_array_equal(valid,np.isfinite(frozen["score"]))
        raw=frozen["raw_scores"];np.testing.assert_array_equal(frozen["score"][valid],raw[valid,1]/raw[valid].sum(1))
        same=list(sorted(frozen.files))
    official=read(args.first/"forward.json");ported=read(args.second/"forward.json")
    assert official["frame_uid"]==ported["frame_uid"]==meta["frame_uid"]
    assert official["optimizer_updates"]==ported["optimizer_updates"]==0
    assert official["parameter_state_sha256"]==ported["parameter_state_sha256"]
    assert official["eval_state_unchanged"] and ported["eval_state_unchanged"]
    wire=read(args.rviz/"wire.json");captures=read(args.rviz/"images/capture.json")
    assert wire["complete"] and wire["own_master_exit"]==0 and captures["pass_checks"]
    assert {r["layer"]:r["width"] for r in wire["observed"]}==expected
    assert all(row["source_indices_match"] for row in wire["observed"])
    records={}
    for row in captures["rows"]:
        file=args.rviz/"images"/(row["layer"]+".png")
        assert hashlib.sha256(file.read_bytes()).hexdigest()==row["sha256"]
        assert row["camera"]==captures["rows"][0]["camera"] and row["count"]==expected[row["layer"]]
        pixels=np.asarray(Image.open(file).convert("RGB"));different=int(np.any(pixels!=pixels[0,0],axis=2).sum())
        assert different==row["colored_pixels"]
        if row["count"]==0:assert different==0
        else:assert different>=300
        records[row["layer"]]=dict(points=row["count"],non_background_pixels=different,sha256=row["sha256"])
    result=dict(status="PASS_BOUNDED_TRAIN_IO_ONLY",source=meta,rows_match_frozen_and_portable=same,
                frozen_forward={k:official[k] for k in ("checkpoint_sha256","epoch","voxels","scored","optimizer_updates","original_index_digest","score_digest")},
                portable_model_code_sha256=ported["model_code_sha256"],wire_layers=expected,images=records,camera=captures["rows"][0]["camera"],
                master_closed=True,no_heldout_evaluation=True,empty_ignore_explicit=True)
    with args.out.open("x") as file:
        json.dump(result,file,indent=2);file.write("\n")
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
