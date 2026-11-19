"""One fixed CUDA logistic probe recipe and its predeclared matched temporal controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import numpy as np

import temporal as ft

SEEDS = (197,241,3090)
POOL, SAMPLE, EPOCHS, BATCH = 2048,1024,48,4096
BASE = {name:group for name,group in ft.FAMILY.items()}
CONTROL = {"COPY":"copy", "SHUFFLE":"shuffle", "DISTANT":"distant", "TK3":"short",
           "LAG2":"lag2", "LAG4":"lag4"}


def save_json(path,payload):
    temporary = path.with_suffix(".partial.json")
    temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
    temporary.replace(path)


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def names(model):
    prefix = CONTROL.get(model,"real")
    return [group if group=="S" else prefix+"_"+group for group in BASE[model]]


def restriction(row):
    if row["domain"] not in ("uchile","ped","follow") or row["role"] not in ("train","val","test"):
        raise ValueError("unregistered domain or role")
    if row["domain"]=="follow" and row["role"]!="test":
        raise ValueError("following domain permitted only for descriptive single-frame evaluation")
    if row.get("history") or row.get("distant_history"):
        if row.get("temporal_status")!="T0" or row["domain"]!="uchile":
            raise ValueError("historical geometry only permitted for approved static public mining frames")


def observation_list(descriptors, row, loader):
    ordinals = []
    result = []
    for item in descriptors:
        if item["event"]!=row["event"] or item["role"]!=row["role"] or item["domain"]!="uchile":
            raise ValueError("history crossed role, event, or public domain")
        ordinals.append(item["ordinal"])
        arrays = loader(item,labels=False)
        if "code" in arrays or "ref" in arrays:
            raise ValueError("label-bearing historical array")
        if not ft.valid_rows(arrays).any():
            return []
        result.append(ft.Observation(arrays))
    if not all(a<b for a,b in zip(ordinals,ordinals[1:])) or any(i>=row["ordinal"] for i in ordinals):
        raise ValueError("noncausal or unordered descriptor")
    return result


def build(row,loader):
    restriction(row)
    start = time.perf_counter()
    frame = loader(row, labels=True)
    xyz = np.asarray(frame["xyz"])
    intensity = np.asarray(frame["intensity"]).reshape(-1)
    valid = ft.valid_rows(frame) & np.asarray(frame["valid"],bool).reshape(-1)
    rows = np.arange(len(xyz))
    if row["role"]=="train":
        eligible = np.flatnonzero(valid & np.isin(frame["code"],[1,2]))
        rng = np.random.default_rng(ft.digest_seed("train-pool/"+row["uid"]))
        rows = np.sort(rng.choice(eligible,min(len(eligible),POOL),replace=False))
    select = rows[valid[rows]]
    result = {name:np.asarray(frame[name])[rows] for name in ("original_index","code","ref")}
    result.update({"valid":valid[rows],"range":np.linalg.norm(xyz[rows],axis=1).astype(np.float32),
                   "intensity":intensity[rows].astype(np.float32)})
    empty = len(select)==0
    if empty:
        for model in BASE:
            for key,group in zip(names(model),BASE[model]):
                result[key]=np.zeros((len(rows),len(ft.GROUPS[group])),np.float32)
            result["avail_"+model]=np.zeros(len(rows),bool)
        result["available"]=np.zeros(len(rows),bool)
        result["n1_features"]=np.zeros((len(rows),8),np.float32)
        result["visibility"]=np.zeros(len(rows),np.uint8)
        result["phase_seconds"]=np.asarray([time.perf_counter()-start,0.,0.])
        result["history_input_points"]=np.int64(0)
        result["copy_input_points"]=np.int64(0)
        result["distant_input_points"]=np.int64(0)
        return result
    current = ft.Observation(frame)
    positions,signals = xyz[select],intensity[select]
    latest = row.get("history",[])[-9:]
    history = observation_list(latest,row,loader)
    more = observation_list(row.get("distant_history",[])[-9:],row,loader)
    loaded = time.perf_counter()
    def expose(name,value):
        if len(select)==len(rows):
            result[name]=np.asarray(value)
        else:
            storage=np.zeros((len(rows),)+value.shape[1:],value.dtype)
            storage[valid[rows]]=value
            result[name]=storage
    expose("S",ft.static_features(current,positions,signals))
    result["avail_S"]=valid[rows]
    def block(prefix, groups, items):
        matrices=ft.histories(current,positions,signals,items,need_f0=prefix=="real")
        for group in groups:
            expose(prefix+"_"+group,matrices[group])
        return matrices
    matrix=block("real",ft.EXTRA,history)
    for model in set(BASE)-set(CONTROL)-{"S"}:
        mask=matrix["F0"][:,-1] if model=="T2" else matrix["MASK"][:,0]
        expose("avail_"+model,mask.astype(bool))
    expose("available",matrix["MASK"][:,0].astype(bool))
    if history:
        lo,hi=history[-1].bounds
        outside=np.any((positions < lo-ft.FINE)|(positions > hi+ft.FINE),axis=1)
        visibility=np.where(matrix["MASK"][:,0]>0,5,np.where(outside,1,4))
    else:
        static_eligible=(row["domain"]=="uchile" and not row["event"].lower().startswith("caren"))
        visibility=np.full(len(positions),2 if static_eligible else 3)
    expose("visibility",visibility.astype(np.uint8))
    expose("n1_features",ft.columns(matrix["F0"][:,3],matrix["F1"][:,0],matrix["F1"][:,1],
           matrix["F2"][:,1],matrix["F3"][:,4],matrix["F4"][:,2],matrix["REC"][:,0],
           matrix["MASK"][:,0]))
    real_done=time.perf_counter()
    perm = np.random.default_rng(ft.digest_seed("order/"+row["uid"])).permutation(len(history))
    if len(perm)>1 and np.array_equal(perm,np.arange(len(perm))):
        perm=np.roll(perm,1)
    variants={"COPY":[current]*len(history),"SHUFFLE":[history[i] for i in perm],
              "DISTANT":more if len(more)==len(history) else [],"TK3":history[-3:]}
    for model,items in variants.items():
        out=block(CONTROL[model],BASE[model][1:],items)
        expose("avail_"+model,out["MASK"][:,0].astype(bool))
    for model,lag in (("LAG2",2),("LAG4",4)):
        differences = (ft.lag_features(history[-lag],positions,signals) if len(history)>=lag
                       else np.zeros((len(positions),len(ft.GROUPS["F0"])),np.float32))
        expose(names(model)[1],differences)
        expose("avail_"+model,differences[:,-1].astype(bool))
    result["phase_seconds"]=np.array([loaded-start,real_done-loaded,time.perf_counter()-real_done])
    result["history_input_points"]=np.int64(sum(len(item.xyz) for item in history))
    result["copy_input_points"]=np.int64(len(current.xyz)*len(history))
    result["distant_input_points"]=np.int64(sum(len(item.xyz) for item in more))
    return result


def cached(row,cache,loader):
    path=cache/(row["uid"]+".npz")
    if not path.exists():
        data=build(row,loader)
        pending=cache/(row["uid"]+"."+str(os.getpid())+".npz")
        np.savez_compressed(pending,**data)
        pending.replace(path)
        return data
    with np.load(path,allow_pickle=False) as payload:
        return dict(payload)


def fit_all(rows,seed,cache,loader,out):
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("select an approved 197 CUDA worker; no CPU fallback for fitting")
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    train={k:[] for k in BASE}
    all_labels=[]
    frame_account=[]
    query_hash=hashlib.sha256()
    for row in rows:
        if row["role"]!="train":
            raise ValueError("nontraining frame passed to fit")
        receipt=cached(row,cache,loader)
        code=receipt["code"]
        eligible=np.flatnonzero(receipt["valid"] & np.isin(code,[1,2]))
        rng=np.random.default_rng(ft.digest_seed(str(seed)+"/"+row["uid"]))
        q=np.sort(rng.choice(eligible,size=min(SAMPLE,len(eligible)),replace=False))
        query_hash.update(row["uid"].encode()+b"\0")
        query_hash.update(receipt["original_index"][q].astype("<i8").tobytes())
        for key in BASE:
            train[key].append(np.column_stack([receipt[name][q] for name in names(key)]))
        all_labels.append((code[q]==2).astype(np.float32))
        frame_account.append({"uid":row["uid"],"domain":row["domain"],"event":row["event"],
                              "points":len(q),"dust":int((code[q]==2).sum()),
                              "person":int((receipt["ref"][q]==1).sum()),"vehicle":int((receipt["ref"][q]==2).sum())})
    label=np.concatenate(all_labels)
    if np.unique(label).size!=2:
        raise ValueError("training evidence lacks both classes")
    target=torch.as_tensor(label,device="cuda")
    ratio=float((label==0).sum()/(label==1).sum())
    positive=torch.tensor(np.sqrt(ratio),device="cuda",dtype=torch.float32)
    weights,log={},{}
    for key in BASE:
        begin=time.perf_counter()
        matrix=np.concatenate(train.pop(key))
        mean=matrix.mean(0,dtype=np.float64).astype(np.float32)
        deviation=matrix.std(0,dtype=np.float64).clip(1e-4,None).astype(np.float32)
        gpu=torch.as_tensor(np.clip((matrix-mean)/deviation,-8.,8.),device="cuda")
        model=torch.nn.Linear(matrix.shape[1],1,device="cuda")
        torch.nn.init.zeros_(model.weight)
        torch.nn.init.zeros_(model.bias)
        optimizer=torch.optim.AdamW(model.parameters(),lr=.012,weight_decay=.01)
        rng=torch.Generator(device="cuda").manual_seed(seed)
        curve=[]
        for epoch in range(EPOCHS):
            order=torch.randperm(len(label),generator=rng,device="cuda")
            epoch_sum=torch.zeros((),device="cuda")
            for ids in torch.split(order,BATCH):
                optimizer.zero_grad()
                loss=torch.nn.functional.binary_cross_entropy_with_logits(
                    model(gpu[ids]).view(-1),target[ids],pos_weight=positive)
                loss.backward()
                optimizer.step()
                epoch_sum+=loss.detach()*len(ids)
            curve.append(float(epoch_sum.item()/len(label)))
        if not np.isfinite(curve).all():
            raise RuntimeError("nonfinite train curve: "+key)
        weights[key]={"mean":mean,"deviation":deviation,"weight":model.weight.detach().cpu().numpy().ravel(),
                      "bias":model.bias.detach().cpu().numpy()}
        log[key]={"seconds":time.perf_counter()-begin,"epoch_losses":curve}
    weightdir=out/"weights"/str(seed)
    weightdir.mkdir(parents=True,exist_ok=True)
    for model,params in weights.items():
        np.savez(weightdir/(model+".npz"),**params)
    save_json(weightdir/"training.json", {"seed":seed,"solver":"CUDA linear AdamW BCE logits",
              "positive_weight":float(positive.item()),"epochs":EPOCHS,"batch_size":BATCH,
              "optimizer_lr":.012,"weight_decay":.01,"training_rows":len(label),
              "per_frame_peak_budget":SAMPLE,"common_query_sha256":query_hash.hexdigest(),
              "training_frames":frame_account,"curves":log,"device":torch.cuda.get_device_name()})
    return weights


def score(row,receipt,models,out,seed):
    target=out/"scores"/str(seed)
    target.mkdir(exist_ok=True,parents=True)
    result={name:receipt[name] for name in ("original_index","code","ref","valid","range","intensity","available","visibility")}
    begin=time.perf_counter()
    for name in BASE:
        matrix=np.column_stack([receipt[key] for key in names(name)])
        param=models[name]
        features=np.clip((matrix-param["mean"])/param["deviation"],-8.,8.)
        logits=features @ param["weight"] + param["bias"]
        value=(1/(1+np.exp(-np.clip(logits,-45.,45.)))).astype(np.float32)
        mask=receipt["avail_"+name].astype(bool)
        if name!="S":
            value[~mask]=result["score_S"][~mask]
        value[~receipt["valid"]]=np.nan
        result["score_"+name]=value
        result["avail_"+name]=mask
    result.update({"uid":np.asarray(row["uid"]),"role":np.asarray(row["role"]),
                   "event":np.asarray(row["event"]),"domain":np.asarray(row["domain"]),
                   "feature_seconds":receipt["phase_seconds"],
                   "history_input_points":receipt["history_input_points"],
                   "distant_input_points":receipt["distant_input_points"],
                   "copy_input_points":receipt["copy_input_points"],
                   "inference_seconds":np.float64(time.perf_counter()-begin)})
    np.savez_compressed(target/(row["uid"]+".npz"),**result)


def cli():
    parser=argparse.ArgumentParser()
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--cache",type=Path)
    parser.add_argument("--seed",type=int,choices=SEEDS,required=True)
    parser.add_argument("--stage",choices=["all","cache","fit"],default="all")
    args=parser.parse_args()
    from data_protocol import load_frame
    manifest=json.loads(args.manifest.read_text())
    frame_rows=manifest["frames"]
    if len({r["uid"] for r in frame_rows})!=len(frame_rows):
        raise ValueError("duplicate center UID")
    for row in frame_rows:
        restriction(row)
    args.out.mkdir(parents=True,exist_ok=True)
    fingerprints={k:hash_file(v) for k,v in {"manifest":args.manifest,
            "features":ft.__file__,"runner":__file__,"loader":sys.modules["data_protocol"].__file__}.items()}
    key=hashlib.sha256(json.dumps(fingerprints,sort_keys=True).encode()).hexdigest()
    cache=(args.cache or args.out/"cache")/key
    cache.mkdir(parents=True,exist_ok=True)
    run=args.out/("run_seed_"+str(args.seed)+".json")
    start=time.perf_counter()
    if args.stage=="cache":
        for index,row in enumerate(frame_rows):
            cached(row,cache,load_frame)
            if index%10==0: print("cached",index+1,len(frame_rows),flush=True)
        return
    if run.exists():
        raise FileExistsError("completed seed output exists: "+str(run))
    fit_start=time.perf_counter()
    weights=fit_all([row for row in frame_rows if row["role"]=="train"],args.seed,cache,load_frame,args.out)
    trained=time.perf_counter()
    for index,row in enumerate(frame_rows):
        if row["role"]!="train":
            score(row,cached(row,cache,load_frame),weights,args.out,args.seed)
        if index%20==0: print("evaluated position",index+1,len(frame_rows),flush=True)
    save_json(run,{"seed":args.seed,"source_hashes":fingerprints,"manifest_frames":len(frame_rows),
            "families":BASE,"train_cache_and_fit_seconds":trained-fit_start,
            "holdout_cache_and_score_seconds":time.perf_counter()-trained,"elapsed":time.perf_counter()-start,
            "cache_key":key,"cache_directory":str(cache),"peak_rss_linux_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "claim":"Source labels from original processing domain. No entity safety certification."})


if __name__=="__main__":
    cli()
