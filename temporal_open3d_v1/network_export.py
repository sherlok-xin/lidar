"""Re-export a frozen best checkpoint in a new job. No optimizer or new fitting."""
import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import torch
from data_protocol import read_manifest, sha_file
from randla_core import upstream_class, MODEL_SHA
from network_train import Store, Timer, infer, write


def main():
    arg=argparse.ArgumentParser()
    arg.add_argument("--training-run",type=Path,required=True)
    arg.add_argument("--manifest",type=Path,required=True)
    arg.add_argument("--fallback",type=Path)
    arg.add_argument("--uid",action="append",default=[])
    args=arg.parse_args()
    run=args.training_run
    freeze=json.loads((run/"config.json").read_text())
    if not torch.cuda.is_available() or freeze["source_sha"]!=MODEL_SHA or sha_file(args.manifest)!=freeze["manifest_sha256"]:
        raise ValueError("wrong evaluation environment or manifest")
    approved=json.loads((Path(__file__).parent/"release_compatibility.json").read_text())
    for filename,digest in freeze["source_sha256"].items():
        actual=sha_file(Path(__file__).parent/filename)
        if actual!=digest and [digest,actual]!=approved.get(filename):
            raise ValueError("checkpoint code mismatch: "+filename)
    stats=json.loads((run/"preprocessing.json").read_text())
    best=torch.load(run/"best.pt",map_location="cpu",weights_only=False)
    if best["identity"]!=stats["uid_hash"]:
        raise ValueError("training state identity")
    opts=SimpleNamespace(**freeze["config"],fallback=args.fallback)
    if opts.model=="N1":
        fb=json.loads((args.fallback/"config.json").read_text())
        if fb["train_uids"]!=freeze["train_uids"] or fb["config"]["seed"]!=opts.seed or fb["config"]["model"]!="N0":
            raise ValueError("unpaired fallback")
    out=Path(os.environ.get("RUN_ROOT") or os.environ["LIDAR_RUN_DIR"]).resolve()
    out.mkdir(parents=True,exist_ok=True)
    if (out/"predictions").exists(): raise FileExistsError("export destination occupied")
    mean=np.array(stats["mean"],np.float32);scale=np.array(stats["scale"],np.float32)
    model=upstream_class(out/"graph")(in_channels=3+len(mean),num_classes=2,seed=opts.seed,num_points=opts.size).to("cuda")
    model.device=torch.device("cuda");model.load_state_dict(best["model"])
    store=Store(opts.model=="N1",stats["grid"],Timer(),out,run/"config.json")
    rows=[r for r in read_manifest(args.manifest)["frames"] if r["role"] in ("val","test") and (r["domain"]!="follow" or r["role"]=="test") and (not args.uid or r["uid"] in args.uid)]
    if args.uid and {r["uid"] for r in rows}!=set(args.uid):raise ValueError("unknown or excluded UID")
    infer(rows,model,store,mean,scale,opts,out)
    write(out/"export.json",dict(model_sha=sha_file(run/"best.pt"),training_run=str(run),
          inputs=freeze["manifest_sha256"],uids=[r["uid"] for r in rows],timing=dict(store.timing)))


if __name__=="__main__":main()
