"""One fixed-seed run. Outputs are scoped to the job, never written to input trees."""
import argparse
import collections
import hashlib
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from sklearn.metrics import average_precision_score
import torch
from data_protocol import read_manifest, load_frame, sha_file
from temporal import network_features
from randla_core import batch, COMMIT, MODEL_SHA, full_predict, patch, training_patch, upstream_class, voxels
from network_probe import calibrate_grid

class Timer(collections.Counter):
    def measure(self,key,start):
        self[key]+=time.perf_counter()-start


def write(path,obj):
    temp=path.with_suffix(path.suffix+".part"); temp.write_text(json.dumps(obj,indent=2)); temp.replace(path)


def save(path,obj):
    temp=path.with_suffix(".tmp"); torch.save(obj,temp); temp.replace(path)


def stable(text):
    return int.from_bytes(hashlib.sha256(str(text).encode()).digest()[:4],"little")


def eligible(row):
    return row["domain"]=="uchile" and row["temporal_status"]=="T0" and len(row["history"])>=3


def in_scope(row,scope):
    if scope=="pair":
        return eligible(row)
    return row["domain"]=="uchile" or (scope=="joint" and row["domain"]=="ped")


class Store:
    def __init__(self,temp,grid,timing,output,config_path=None):
        self.temp,self.grid,self.timing=temp,grid,timing
        # Separate caches even if a user reuses a directory basename. Historical
        # manifest receipt binds source, label version, schema and source indices.
        cache_identity = sha_file(config_path or (output/"config.json"))
        self.path=Path(os.environ.get("FEATURE_CACHE",str(output/"cache")))/cache_identity
        self.path.mkdir(parents=True,exist_ok=True)
        self.receipts={}

    def get(self,row):
        path=self.path/(row["uid"]+".npz")
        if path.is_file():
            with np.load(path,allow_pickle=False) as archive:
                return dict(archive)
        begin=time.perf_counter()
        current=load_frame(row)
        self.timing.measure("read_current",begin)
        extra=None
        available=np.zeros(len(current["xyz"]),bool)
        if self.temp:
            begin=time.perf_counter()
            historic=[load_frame(item,labels=False) for item in row["history"][-9:]] if eligible(row) else []
            self.timing.measure("read_history",begin)
            begin=time.perf_counter()
            extra=network_features(current,historic)
            available=extra[:,-1]>0
            self.timing.measure("history_features",begin)
        begin=time.perf_counter()
        frame=voxels(current,extra,self.grid)
        if frame is None:
            frame=dict(rows=np.empty(0,np.int64),points=np.empty((0,3),np.float32),feat=np.empty((0,9 if self.temp else 1),np.float32),
                       label=np.empty(0,np.uint8),pre=np.zeros(3,np.int64),post=np.zeros(3,np.int64),proj=np.empty(0,np.int32))
        frame.update({key:current[key] for key in ("original_index","code","ref","valid")})
        frame["temporal_available"]=available
        self.timing.measure("preprocess_projection",begin)
        self.receipts[row["uid"]]=dict(event=row["event"],role=row["role"],pre=frame["pre"].tolist(),post=frame["post"].tolist(),
            before_by_reference={str(i):int(np.count_nonzero(current["ref"][frame["rows"]]==i)) for i in (0,1,2,3,4,5)},
            after_original_rows_class_disagreement={str(i):int(np.count_nonzero((current["ref"][frame["rows"]]==i)&
                (current["code"][frame["rows"]]!=frame["label"][frame["proj"]]))) for i in (0,1,2,3,4,5)})
        temp=path.with_suffix(".tmp")
        with temp.open("wb") as stream: np.savez(stream,**frame)
        temp.replace(path)
        return frame


def state(model,opt,scheduler,epoch,rng,best,stale,identity):
    return dict(model=model.state_dict(),optimizer=opt.state_dict(),scheduler=scheduler.state_dict(),epoch=epoch,
                numpy_rng=rng.bit_generator.state,python_rng=random.getstate(),torch_rng=torch.get_rng_state(),
                cuda_rng=torch.cuda.get_rng_state_all(),best=best,stale=stale,identity=identity)


def infer(rows,model,store,mean,scale,opts,output=None):
    model.eval()
    by_event=collections.defaultdict(list)
    timing=store.timing
    for row in rows:
        frame=store.get(row)
        n=len(frame["original_index"])
        if opts.model=="N1" and output is not None:
            fallback=Path(opts.fallback)/"predictions"/row["role"]/(row["uid"]+".npz")
            if not fallback.exists():
                raise RuntimeError(f"paired single-frame score not ready: {fallback}")
            with np.load(fallback) as other:
                if not np.array_equal(other["original_index"],frame["original_index"]) or not np.array_equal(other["code"],frame["code"]):
                    raise RuntimeError("single-frame fallback index/label mismatch")
                fallback_raw = other["raw_scores"]
                fallback_scores = other["score"]
        begin=time.perf_counter()
        raw,score=full_predict(model,frame if len(frame["points"]) else None,n,mean,scale,opts.size,
                               stable((opts.seed,row["uid"])),"cuda",opts.vote_batch)
        timing.measure("network_vote_including_patch_knn_projection",begin)
        if opts.model=="N1" and output is not None:
            missing=~frame["temporal_available"]
            score[missing],raw[missing]=fallback_scores[missing],fallback_raw[missing]
        mask=(frame["code"]>0)&np.isfinite(score)
        by_event[row["event"]].append((frame["code"][mask]==2,score[mask]))
        if output is not None:
            prefix=output/"predictions"/row["role"]; prefix.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(prefix/(row["uid"]+".npz"),raw_scores=raw,score=score,predicted_mask=np.isfinite(score),
                      original_index=frame["original_index"],code=frame["code"],ref=frame["ref"],temporal_available=frame["temporal_available"])
    ap={}
    for event,pairs in by_event.items():
        y=np.concatenate([p[0] for p in pairs]); s=np.concatenate([p[1] for p in pairs])
        ap[event]=float(average_precision_score(y,s)) if y.any() else None
    clean=[value for value in ap.values() if value is not None]
    return (float(np.mean(clean)) if clean else None),ap


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--model",choices=["N0","N1"],required=True)
    parser.add_argument("--scope",choices=["public","joint","pair"],required=True)
    parser.add_argument("--seed",type=int,required=True)
    parser.add_argument("--size",type=int,default=4096);parser.add_argument("--batch",type=int,default=4)
    parser.add_argument("--vote-batch",type=int,default=6);parser.add_argument("--epochs",type=int,default=30)
    parser.add_argument("--interval",type=int,default=3);parser.add_argument("--patience",type=int,default=4)
    parser.add_argument("--fallback");parser.add_argument("--resume",type=Path)
    parser.add_argument("--manifest",type=Path,default=Path(__file__).parent/"manifest.json")
    opts=parser.parse_args()
    if not torch.cuda.is_available() or (opts.model=="N1" and (opts.scope!="pair" or not opts.fallback)):
        raise RuntimeError("expected a single CUDA device and paired N0 for N1")
    output=Path(os.environ.get("RUN_ROOT") or os.environ["LIDAR_RUN_DIR"]).resolve()
    output.mkdir(parents=True,exist_ok=True)
    timing=Timer()
    start=time.perf_counter()
    rng=np.random.default_rng(opts.seed);random.seed(opts.seed);torch.manual_seed(opts.seed)
    torch.backends.cudnn.benchmark=False
    rows=read_manifest(opts.manifest)["frames"]
    train=[row for row in rows if row["role"]=="train" and in_scope(row,opts.scope)]
    val=[row for row in rows if row["role"]=="val" and in_scope(row,opts.scope)]
    assert train and val and all(r["domain"]!="follow" for r in train+val)
    grid=float(np.median([calibrate_grid(load_frame(row,labels=False)["xyz"]) for row in train[::max(1,len(train)//12)][:12]]))
    freeze={"protocol":"v1-4096", "upstream_commit":COMMIT,"source_sha":MODEL_SHA,"manifest_sha256":sha_file(opts.manifest),
            "config":{k:v for k,v in vars(opts).items() if k not in ("manifest","resume","fallback")}, "grid_train_only":grid,
            "train_uids":[r["uid"] for r in train],"selection_val_uids":[r["uid"] for r in val],
            "source_sha256":{p.name:sha_file(p) for p in Path(__file__).parent.glob("*.py")}}
    if opts.fallback:
        meta=json.loads((Path(opts.fallback)/"config.json").read_text())
        if meta["manifest_sha256"]!=freeze["manifest_sha256"] or meta["config"]["model"]!="N0" or meta["config"]["seed"]!=opts.seed or meta["train_uids"]!=freeze["train_uids"] or meta["selection_val_uids"]!=freeze["selection_val_uids"]:
            raise RuntimeError("invalid paired fallback identity")
    identity=hashlib.sha256(json.dumps(freeze,sort_keys=True).encode()).hexdigest()
    write(output/"config.json",freeze)
    store=Store(opts.model=="N1",grid,timing,output)
    counts=np.zeros(3,np.int64);moments=[]
    for row in train:
        frame=store.get(row);counts+=frame["post"]
        feature=frame["feat"][::max(1,len(frame["feat"])//512)][:512]
        if len(feature):moments.append(feature)
    stats=np.concatenate(moments);mean=stats.mean(0);scale=np.maximum(stats.std(0),1e-5)
    class_weights=1/np.sqrt(np.maximum(counts[1:],1));class_weights=class_weights/class_weights.mean()
    weights=torch.tensor(class_weights,device="cuda",dtype=torch.float32)
    write(output/"preprocessing.json",dict(mean=mean.tolist(),scale=scale.tolist(),class_weights=class_weights.tolist(),
          counts=counts.tolist(),training_only=True,grid=grid,uid_hash=identity))
    cls=upstream_class(output/"graph")
    model=cls(in_channels=3+len(mean),num_classes=2,seed=opts.seed,num_points=opts.size).to("cuda")
    model.device=torch.device("cuda")
    opt=torch.optim.Adam(model.parameters(),lr=.001)
    scheduler=torch.optim.lr_scheduler.ExponentialLR(opt,gamma=.9886)
    epoch0=0;best=-1;stale=0
    if opts.resume:
        restored=torch.load(opts.resume,map_location="cpu",weights_only=False)
        if restored["identity"]!=identity: raise ValueError("resume identity")
        model.load_state_dict(restored["model"]);opt.load_state_dict(restored["optimizer"]);scheduler.load_state_dict(restored["scheduler"])
        rng.bit_generator.state=restored["numpy_rng"];random.setstate(restored["python_rng"])
        torch.set_rng_state(restored["torch_rng"]);torch.cuda.set_rng_state_all(restored["cuda_rng"])
        epoch0,best,stale=restored["epoch"],restored["best"],restored["stale"]
        if not (opts.resume.parent/"best.pt").is_file():raise RuntimeError("cannot recover prior selected checkpoint")
        import shutil
        if (opts.resume.parent/"best.pt").resolve()!=(output/"best.pt").resolve():
            shutil.copyfile(opts.resume.parent/"best.pt",output/"best.pt")
    expected=int(np.ceil(len(train)/opts.batch))
    print(f"TRAIN frame_count={len(train)} batches_per_epoch={expected} validation={len(val)} grid={grid} device={model.device}",flush=True)
    def prepare(arg):
        ix,seed=arg
        row=train[ix];frame=store.get(row)
        if not len(frame["points"]):return row,None,None
        ids,labels=training_patch(frame,opts.size,np.random.default_rng(seed))
        return row,patch(frame,ids,mean,scale),labels
    for epoch in range(epoch0+1,opts.epochs+1):
        begin=time.perf_counter();model.train()
        order=rng.permutation(len(train))
        args=list(zip(order,rng.integers(0,2**32,size=len(order))))
        contributed=collections.defaultdict(lambda:np.zeros(3,np.int64));unique=set();updates=0;skipped=0;loss_sum=0
        with ThreadPoolExecutor(max_workers=4) as executor:
            prepared=iter(executor.map(prepare,args))
            import itertools
            while True:
                pack=list(itertools.islice(prepared,opts.batch))
                if not pack:break
                pack=[entry for entry in pack if entry[1] is not None]
                if not pack:skipped+=1;continue
                ids=torch.from_numpy(np.stack([entry[2] for entry in pack]).astype(np.int64)).to("cuda")
                mask=ids>0
                if not mask.any():skipped+=1;continue
                opt.zero_grad(set_to_none=True); logits=model(batch([entry[1] for entry in pack]))
                loss=torch.nn.functional.cross_entropy(logits[mask],ids[mask]-1,weight=weights)
                if not torch.isfinite(loss): raise FloatingPointError("nonfinite train loss")
                loss.backward();opt.step();updates+=1;loss_sum+=float(loss.detach())
                for row,_,labels in pack:
                    unique.add(row["uid"]);contributed[row["domain"]]+=np.bincount(labels,minlength=3)
        if not updates:raise RuntimeError("empty training epoch")
        scheduler.step()
        record=dict(epoch=epoch,updates=updates,skipped_empty_batches=skipped,unique_training_frames=len(unique),
                    counts_ignore_non_dust_dust={k:v.tolist() for k,v in contributed.items()},
                    mean_step_ce=loss_sum/updates,train_seconds=time.perf_counter()-begin)
        if epoch%opts.interval==0 or epoch==opts.epochs:
            now=time.perf_counter()
            metric,events=infer(val,model,store,mean,scale,opts)
            if metric is None:raise ValueError("no validation event supports dust AP")
            record.update(validation_macro_AP=metric,event_AP=events,validation_seconds=time.perf_counter()-now)
            if metric>best:
                best=metric;stale=0
                save(output/"best.pt",state(model,opt,scheduler,epoch,rng,best,stale,identity))
            else:stale+=1
        save(output/"last.pt",state(model,opt,scheduler,epoch,rng,best,stale,identity))
        with (output/"epochs.jsonl").open("a") as log: log.write(json.dumps(record)+"\n")
        print(json.dumps(record),flush=True)
        if stale>=opts.patience:break
    beststate=torch.load(output/"best.pt",map_location="cpu",weights_only=False)
    assert beststate["identity"]==identity
    model.load_state_dict(beststate["model"])
    for split in ("val","test"):
        evaluate=[r for r in rows if r["role"]==split and (r["domain"]!="follow" or split=="test")]
        infer(evaluate,model,store,mean,scale,opts,output)
    write(output/"voxels.json",store.receipts)
    write(output/"finished.json",dict(selected_epoch=beststate["epoch"],selected_macro_AP=best,
          total_seconds=time.perf_counter()-start,timers=dict(timing),gpu_max_bytes=torch.cuda.max_memory_allocated(),
          gpu=torch.cuda.get_device_name(0),checkpoint_sha=sha_file(output/"best.pt"),identity=identity))


if __name__=="__main__":
    main()
