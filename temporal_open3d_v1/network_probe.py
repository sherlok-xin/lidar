import argparse
import hashlib
import json
import os
import time
from pathlib import Path
import numpy as np
import torch
from scipy.spatial import cKDTree
from randla_core import upstream_class, batch, voxels, patch, full_predict, training_patch, COMMIT, MODEL_SHA


def calibrate_grid(xyz):
    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    distances = cKDTree(xyz).query(xyz[::max(1,len(xyz)//1024)],k=2)[0][:,1]
    positive=distances[np.isfinite(distances) & (distances>0)]
    if not len(positive):
        raise ValueError("cannot calibrate grid from training inputs")
    return .5*float(np.median(positive))


def main():
    output = Path(os.environ.get("RUN_ROOT") or os.environ["LIDAR_RUN_DIR"]).resolve()
    if not torch.cuda.is_available():
        raise RuntimeError("GPU required")
    torch.manual_seed(197)
    rng=np.random.default_rng(197)
    frame_manifest=json.loads(Path(os.environ["TINYFIT_MANIFEST"]).read_text())
    row=next(r for r in frame_manifest["frames"] if r["domain"]=="uchile" and r["role"]=="train" and r["subset"]!="caren" and min(r["dust"],r["non_dust"])>=3000)
    xyz, intensity, segment=[np.load(p) for p in row["source_files"]]
    assert set(np.unique(segment))=={0,1}
    code=np.where(segment.ravel()==0,2,1).astype(np.uint8)
    cloud=dict(xyz=xyz,intensity=intensity,code=code,valid=np.ones(len(code),bool))
    grid=calibrate_grid(xyz)
    frame=voxels(cloud,None,grid)
    mean,scale=frame["feat"].mean(0),np.maximum(frame["feat"].std(0),1e-6)
    size=4096
    indices,labels=training_patch(frame,size,rng)
    for _ in range(20):
        if len(np.unique(labels[labels>0]))==2: break
        indices,labels=training_patch(frame,size,rng)
    if len(np.unique(labels[labels>0]))!=2:
        raise RuntimeError("tinyfit fixture misses a class")
    tensors=batch([patch(frame,indices,mean,scale)])
    cls=upstream_class(output/"graph")
    model=cls(in_channels=4,num_classes=2,seed=197,num_points=size).to("cuda")
    model.device=torch.device("cuda")
    labels=torch.from_numpy(labels.astype(np.int64)).to("cuda")
    opt=torch.optim.Adam(model.parameters(),lr=.002)
    weights=torch.tensor(1/np.maximum(np.bincount(labels.cpu().numpy(),minlength=3)[1:],1),device="cuda",dtype=torch.float32)
    curve=[]
    orig=model.fc0.weight.detach().clone()
    start=time.perf_counter()
    for step in range(48):
        opt.zero_grad()
        logits=model(tensors)[0]
        loss=torch.nn.functional.cross_entropy(logits[labels>0],labels[labels>0]-1,weight=weights)
        loss.backward()
        if not torch.isfinite(loss) or not torch.isfinite(model.fc0.weight.grad).all():
            raise FloatingPointError("nonfinite update")
        opt.step()
        curve.append(float(loss.detach()))
    model.eval()
    with torch.no_grad():
        prediction=model(tensors)
        ckpt=output/"probe.pt"
        torch.save(model.state_dict(),ckpt)
        clone=cls(in_channels=4,num_classes=2,seed=197,num_points=size).to("cuda")
        clone.device=model.device
        clone.load_state_dict(torch.load(ckpt,map_location="cuda",weights_only=True)); clone.eval()
        maximum=float((clone(tensors)-prediction).abs().max())
    assert maximum==0 and not torch.equal(orig,model.fc0.weight)
    trained=time.perf_counter()-start
    start=time.perf_counter()
    raw,score=full_predict(model,frame,len(code),mean,scale,size,197,"cuda")
    voted=time.perf_counter()-start
    np.savez_compressed(output/"full.npz",raw_scores=raw,score=score,code=code,original_index=np.arange(len(code)))
    outcome={"commit":COMMIT,"source_sha256":MODEL_SHA,"model_path":str(output/"graph"/"pinned_open3d_ml_randlanet.py"),
             "frame_key":row["key"],"split":row["role"],"input_sha256":row["source_sha256"],"seed":197,
             "gpu":torch.cuda.get_device_name(0),"torch":torch.__version__,"valid_full_scores":int(np.isfinite(score).sum()),"points":len(code),
             "train_patch_class_counts":np.bincount(labels.cpu().numpy(),minlength=3).tolist(),"grid":grid,
             "pre":frame["pre"].tolist(),"post":frame["post"].tolist(),"seconds_per_update":trained/len(curve),
             "full_vote_seconds":voted,"gpu_peak_bytes":torch.cuda.max_memory_allocated(),"reload_max_abs":maximum,
             "tinyfit_ce":curve,"tinyfit_improvement":float(np.mean(curve[:5])-np.mean(curve[-5:]))}
    (output/"probe.json").write_text(json.dumps(outcome,indent=2))
    if outcome["tinyfit_improvement"]<=0 or not np.isfinite(score[frame["rows"]]).all():
        raise AssertionError(outcome)
    print(json.dumps(outcome),flush=True)

if __name__=="__main__":
    main()
