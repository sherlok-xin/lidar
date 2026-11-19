"""Read one already-used public training frame; optionally validate a frozen N0 forward."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import numpy as np

PUBLIC_SAMPLE = "interior1/Area_1/amtc_068"
CHECKPOINT_SHA = "acc9d569980701d45e43899ddbeaa355954b012a405af4ac49ecd7e447dba595"
FROZEN_CORE_SHA = "2c16cffb2c6671740a16d233091f3ba19ceb05263874685fafc2a9cd4ecbfc27"
PORTABLE_CORE_SHA = "acf48a7fceed16ad72646cd7905572fdad3e4fc57ed5fe3bee839e937a06b50c"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def signature(a):
    arr = np.ascontiguousarray(a)
    return dict(shape=list(arr.shape), dtype=arr.dtype.str, sha256=digest(arr.tobytes()))


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream,indent=2);stream.write("\n")


def verify_and_load(row, root):
    from datahub import read_frame
    if row["dataset_id"]!="uchile" or row["split"]!="train" or row["source_ref"]!=PUBLIC_SAMPLE:
        raise ValueError("this bounded validation accepts only the declared public training frame")
    all_rows=read_frame(row,data_root=root,valid_only=False)
    only=read_frame(row,data_root=root,valid_only=True)
    valid=all_rows["stored_valid_mask"]
    original=all_rows["source_point_index"]
    raw=all_rows["semantic_raw"]
    task=all_rows["task_label"]
    attributes=all_rows["attributes"]
    if not all_rows["attribute_available"]["intensity"]["present"]:
        raise ValueError("frozen N0 requires intensity")
    if not np.array_equal(original,np.arange(len(valid),dtype=original.dtype)):
        raise ValueError("source NPY rows are not identical")
    for full,filtered in ((original,only["source_point_index"]),(all_rows["xyz"],only["xyz"]),
                          (attributes["intensity"],only["attributes"]["intensity"]),
                          (task,only["task_label"]),(raw,only["semantic_raw"])):
        np.testing.assert_array_equal(full[valid],filtered)
    if not np.array_equal(task[valid],np.where(raw[valid]==0,2,1)):
        raise ValueError("UCHILE source label mapping mismatch")
    if not np.array_equal(all_rows["supervision_mask"],task!=0):
        raise ValueError("supervision mask mismatch")
    return dict(xyz=all_rows["xyz"],intensity=attributes["intensity"],source_point_index=original,valid=valid,
                semantic_raw=raw,task_label=task,supervision_mask=all_rows["supervision_mask"])


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("mode",choices=["export","infer"])
    cli.add_argument("--output",type=Path,required=True)
    cli.add_argument("--data-root",type=Path,default=os.environ.get("DATA_ROOT"))
    cli.add_argument("--derived-root",type=Path,default=os.environ.get("DERIVED_ROOT"))
    cli.add_argument("--receipt",type=Path)
    cli.add_argument("--checkpoint-dir",type=Path,default=os.environ.get("CHECKPOINT_DIR"))
    cli.add_argument("--model-code",type=Path,default=os.environ.get("MODEL_CODE_ROOT"))
    args=cli.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    if args.mode=="export":
        from datahub import find_frame
        row=find_frame(args.derived_root,"uchile",PUBLIC_SAMPLE)
    else:
        meta=json.loads(args.receipt.read_text());row=meta["row"]
    cloud=verify_and_load(row,args.data_root)
    signatures={k:signature(v) for k,v in cloud.items()}
    if args.mode=="export":
        view=dict(frame_uid=row["frame_uid"],source_ref=row["source_ref"],frame_id=row["coordinate_frame"],
                  split=row["split"],stamp_ns=row["header_stamp_ns"],stamp_source=row["timestamp_source"],
                  counts=dict(stored=len(cloud["valid"]),valid=int(cloud["valid"].sum()),supervised=int(cloud["supervision_mask"].sum()),
                              dust=int((cloud["task_label"]==2).sum()),ignored=int((~cloud["supervision_mask"]).sum())))
        with (args.output/"sample.npz").open("xb") as stream:np.savez_compressed(stream,**cloud)
        write(args.output/"review.json",view);write(args.output/"input.json",dict(row=row,arrays=signatures))
        print(json.dumps(view));return
    if signatures!=meta["arrays"]:raise ValueError("remote reader differs from registered sample")
    import torch
    if not torch.cuda.is_available():raise RuntimeError("designated GPU required")
    model_dir=args.checkpoint_dir
    config=json.loads((model_dir/"config.json").read_text())
    source_key=row["source_ref"].replace("/","__")
    permitted=[k for k in config["train_uids"] if k==source_key]
    if permitted!=[source_key] or config["config"]["model"]!="N0" or config["config"]["scope"]!="public":
        raise ValueError("source is not on the frozen training list")
    if digest((model_dir/"best.pt").read_bytes())!=CHECKPOINT_SHA:
        raise ValueError("refusing unverified checkpoint")
    model_code_sha=digest((args.model_code/"randla_core.py").read_bytes())
    if config["source_sha256"]["randla_core.py"]!=FROZEN_CORE_SHA or model_code_sha not in (FROZEN_CORE_SHA,PORTABLE_CORE_SHA):
        raise ValueError("frozen inference code does not match run receipt")
    sys.path.insert(0,str(args.model_code.resolve()))
    import randla_core
    if Path(randla_core.__file__).resolve()!=args.model_code.resolve()/"randla_core.py":raise ValueError("unexpected model module")
    if os.getenv("OPEN3D_ML_ROOT"):
        randla_core.UPSTREAM=Path(os.environ["OPEN3D_ML_ROOT"]).resolve()
    inputs=dict(xyz=cloud["xyz"],intensity=cloud["intensity"],code=cloud["task_label"],valid=cloud["valid"])
    preprocess=json.loads((model_dir/"preprocessing.json").read_text())
    checkpoint=torch.load(model_dir/"best.pt",map_location="cpu",weights_only=False)
    if checkpoint["identity"]!=preprocess["uid_hash"]:raise ValueError("mismatched preprocessing")
    options=config["config"];model=randla_core.upstream_class(args.output/"model_graph")(
        in_channels=4,num_classes=2,seed=options["seed"],num_points=options["size"]).to("cuda")
    model.load_state_dict(checkpoint["model"]);model.eval();model.device=torch.device("cuda")
    before=digest(b"".join(t.detach().cpu().contiguous().numpy().tobytes() for t in model.state_dict().values()))
    start=time.monotonic()
    with torch.inference_mode():
        grid=randla_core.voxels(inputs,None,preprocess["grid"])
        fixed_seed=int.from_bytes(hashlib.sha256(str((options["seed"],source_key)).encode()).digest()[:4],"little")
        raw,score=randla_core.full_predict(model,grid,len(inputs["xyz"]),np.asarray(preprocess["mean"],np.float32),
            np.asarray(preprocess["scale"],np.float32),options["size"],fixed_seed,"cuda",options["vote_batch"])
    elapsed=time.monotonic()-start
    after=digest(b"".join(t.detach().cpu().contiguous().numpy().tobytes() for t in model.state_dict().values()))
    valid=inputs["valid"] & np.isfinite(inputs["intensity"])
    np.testing.assert_array_equal(valid,np.isfinite(score))
    np.testing.assert_array_equal(score[valid],(raw[valid,1]/raw[valid].sum(axis=1)))
    np.testing.assert_array_equal(cloud["source_point_index"][grid["rows"]],np.flatnonzero(valid))
    if before!=after or not np.isfinite(raw).all():raise ValueError("frozen evaluation contract")
    with (args.output/"prediction.npz").open("xb") as stream:
        np.savez_compressed(stream,source_point_index=cloud["source_point_index"],raw_scores=raw,score=score,
                            valid=valid,model_proj_voxel=grid["proj"],stored_rows=grid["rows"])
    result=dict(status="PASS_TRAIN_INPUT_FORWARD_ONLY",frame_uid=row["frame_uid"],source_ref=row["source_ref"],
        split=row["split"],original_identity="coord.npy row",voxel_projection_is_interpolation=True,source_and_remote_arrays_match=True,
        forward_seconds=elapsed,points=len(score),scored=int(valid.sum()),voxels=len(grid["points"]),
        checkpoint_sha256=CHECKPOINT_SHA,model_code_sha256=model_code_sha,epoch=checkpoint["epoch"],parameter_state_sha256=before,eval_state_unchanged=True,
        torch_version=torch.__version__,gpu=torch.cuda.get_device_name(0),optimizer_updates=0,performance_metrics_computed=False,
        original_index_digest=signature(cloud["source_point_index"]),score_digest=signature(score))
    write(args.output/"forward.json",result);print(json.dumps(result))


if __name__=="__main__":main()
