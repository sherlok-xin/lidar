"""Read-only independent ranking, role, source-row and prediction oracle."""
import argparse
import csv
import os
import hashlib
import json
from collections import defaultdict, Counter
from functools import lru_cache
from pathlib import Path

import numpy as np


ROOT=Path(__file__).resolve().parents[1]
PROJECT=Path(os.environ.get("HISTORICAL_ROOT","historical")).resolve()
RUNS=Path(os.environ.get("RUNS_ROOT",PROJECT/"runs"))
DATA=Path(os.environ.get("DATA_ROOT","datasets")).resolve()
NP=PROJECT/"runs/temporal_randla_probe_v1_20261119"
MB=ROOT/"manifest.json"
FROZEN="4a9355eb7318715d4e370a9c6a73bad1ffa8721f1ca14abcfefc257114a38425"
MODEL_SHA="8d7d3457ed653a5ead2ffbdca01388bf95e3cd9b102aea19965dae743ff17839"


def sha(p):
    digest=hashlib.sha256()
    with Path(p).open("rb") as f:
        for data in iter(lambda:f.read(1024**2),b""):digest.update(data)
    return digest.hexdigest()


def read(p):
    return json.loads(Path(p).read_bytes())


def ranking(scores,positive):
    if not len(scores) or not np.any(positive):
        return None,None
    order=np.argsort(scores,kind="stable")[::-1]
    s=np.asarray(scores)[order]
    y=np.asarray(positive,dtype=np.int64)[order]
    final=np.r_[np.flatnonzero(s[1:]!=s[:-1]),len(s)-1]
    hits=np.cumsum(y)[final]
    recall=hits/y.sum()
    precision=hits/(final+1)
    delta=np.diff(np.r_[0.,recall])
    return float(np.dot(delta,precision)),float(np.dot(delta,(np.r_[1.,precision[:-1]]+precision)/2))


def operating(scores,code,ref,threshold):
    finite=np.isfinite(scores)
    candidate=finite&(scores>=threshold)
    keep=finite&~candidate
    return dict(tp=int((candidate&(code==2)).sum()),fp=int((candidate&(code==1)).sum()),fn=int((keep&(code==2)).sum()),
                tn=int((keep&(code==1)).sum()),person_fp=int((candidate&(ref==1)&(code==1)).sum()),person=int((finite&(ref==1)&(code==1)).sum()),
                vehicle_fp=int((candidate&(ref==2)&(code==1)).sum()),vehicle=int((finite&(ref==2)&(code==1)).sum()),ignored_candidate=int((candidate&(code==0)).sum()),unscored_labelled=int((~finite&(code!=0)).sum()))


def validation_threshold(records,frame_support):
    scores,code,ref=(np.concatenate(x) for x in zip(*records))
    valid=(code>0)&np.isfinite(scores)
    people=np.sort(scores[valid&(ref==1)&(code==1)])
    cars=np.sort(scores[valid&(ref==2)&(code==1)])
    dust=np.sort(scores[valid&(code==2)])
    out=dict(person=len(people),vehicle=len(cars),dust=len(dust),support_frames=dict(frame_support))
    if min(len(cars),len(people))<100 or min(frame_support["person"],frame_support["vehicle"])<3 or not len(dust):
        return dict(out,status="UNAVAILABLE",threshold=None)
    candidates=np.unique(scores[valid])
    counts=lambda group:len(group)-np.searchsorted(group,candidates,side="left")
    person,vehicle,dust_hit=[counts(group) for group in (people,cars,dust)]
    safe=((100*person<=len(people))&(100*vehicle<=len(cars)))
    feasible=safe&(10*dust_hit>=len(dust))
    out["max_budget_recall"]=float(np.max(dust_hit[safe],initial=0)/len(dust))
    if not feasible.any():return dict(out,status="INFEASIBLE",threshold=None)
    pos=np.flatnonzero(feasible)
    idx=pos[np.lexsort((-candidates[pos],person[pos]+vehicle[pos],-dust_hit[pos]))[0]]
    return dict(out,status="AVAILABLE",threshold=float(candidates[idx]),dust_tp=int(dust_hit[idx]),person_fp=int(person[idx]),vehicle_fp=int(vehicle[idx]))


def validate_preflight(rows):
    toy=np.asarray([.9,.9,.3,.1])
    assert np.allclose(ranking(toy,np.asarray([1,0,1,0])),[7/12,2/3])
    assert ranking(toy,np.zeros(4,bool))==(None,None)
    sanity=operating(np.asarray([.9,.8,np.nan,.1]),np.asarray([0,1,2,1]),np.asarray([4,2,3,1]),.5)
    assert (sanity["ignored_candidate"],sanity["vehicle_fp"],sanity["person_fp"],sanity["fn"],sanity["tn"],sanity["unscored_labelled"])==(1,1,0,0,1,1)
    assert sha(MB)==FROZEN
    releases={}
    for path in (PROJECT/"temporal_open3d_v1/releases").glob("*/release.json"):
        entries=read(path)
        assert sha(path)[:20]==path.parent.name
        for rel,expected in entries.items():assert sha(path.parent/rel)==expected,(path.parent.name,rel)
        releases[path.parent.name]=entries
    roles={r["uid"]:r for r in rows}
    assert len(roles)==len(rows)
    events=defaultdict(set)
    history_count=0
    for row in rows:
        if row["domain"]=="uchile":events[row["event"]].add(row["role"])
        if row["domain"]=="follow":assert row["role"]=="test" and not row["history"]
        for group in ("history","distant_history"):
            hist=row[group]
            assert all(i["context_only"] and i["ordinal"]<row["ordinal"] and (i["domain"],i["event"],i["role"])==(row["domain"],row["event"],row["role"]) for i in hist)
            assert all(a["ordinal"]+1==b["ordinal"] for a,b in zip(hist,hist[1:]))
        history_count+=len(row["history"])
    assert all(len(x)==1 for x in events.values())
    probe=read(NP/"probe.json")
    assert probe["gpu"]=="NVIDIA GeForce RTX 3090" and probe["split"]=="train"
    path=DATA/"dataset_polvo"/probe["frame_key"].removeprefix("public/")
    with np.load(NP/"full.npz") as data:
        y=np.load(path/"segment.npy")==0
        scores=data["score"]; raw=data["raw_scores"]
        assert np.array_equal(data["original_index"],np.arange(len(y))) and np.array_equal(data["code"],y.astype(int)+1)
        assert np.all(raw.sum(1)>0) and np.array_equal(scores,raw[:,1]/raw.sum(1))
        assert np.isfinite(scores).all() and len(y)==probe["valid_full_scores"]
    assert probe["tinyfit_ce"][-1]<probe["tinyfit_ce"][0] and probe["reload_max_abs"]==0
    graph=(NP/"graph/pinned_open3d_ml_randlanet.py").read_text()
    upstream=Path(os.environ.get("OPEN3D_ML_ROOT","third_party/Open3D-ML"))
    official=upstream/"ml3d/torch/models/randlanet.py"
    assert sha(official)==probe["source_sha256"]==MODEL_SHA
    import ast
    def forward_hashes(source):
        return {(cls.name,func.name):ast.dump(func,include_attributes=False) for cls in ast.parse(source).body if isinstance(cls,ast.ClassDef) for func in cls.body if isinstance(func,ast.FunctionDef) and func.name=="forward"}
    forwards=forward_hashes(graph)
    assert len(forwards)>3 and forward_hashes(official.read_text())==forwards
    assert sha(NP/"graph/upstream.LICENSE")==sha(upstream/"LICENSE")
    replay={}
    directory=RUNS/"temporal_randla_checkpoint_qa197"
    if (directory/"export.json").exists():
        receipt=read(directory/"export.json")
        original_run=RUNS/Path(receipt["training_run"]).name
        assert sha(original_run/"best.pt")==receipt["model_sha"] and receipt["inputs"]==FROZEN
        for uid in receipt["uids"]:
            role=roles[uid]["role"]
            rel=Path("predictions")/role/(uid+".npz")
            with np.load(directory/rel) as repeat,np.load(original_run/rel) as initial:
                assert set(repeat)==set(initial)
                for name in initial:
                    assert np.array_equal(initial[name],repeat[name],equal_nan=True),(uid,name)
                replay[uid]=len(repeat["score"])
    return dict(release_files_verified={k:len(v) for k,v in releases.items()},source_roles={role:sum(1 for v in events.values() if v=={role}) for role in ("train","val","test")},ordered_primary_history_references=history_count,
                upstream_forward_functions_identical=len(forwards),probe_sha=sha(NP/"probe.json"),tinyfit_count_by_class=probe["train_patch_class_counts"],tinyfit_steps=len(probe["tinyfit_ce"]),overfit_ce=[probe["tinyfit_ce"][0],probe["tinyfit_ce"][-1]],
                original_rows_probe=len(scores),probe_average_precision=ranking(scores,y)[0],probe_reload_max_abs_reported=probe["reload_max_abs"],checkpoint_sha=sha(NP/"probe.pt"),best_checkpoint_actual_reexport_equal_rows=replay,scope="Whole-frame probe and independent process re-export files checked; not an independent GPU training run.")


def independent_reference(row):
    if row["domain"]=="uchile":
        source=DATA/"dataset_polvo"/row["source"]
        c=np.load(source/"segment.npy")
        assert np.isin(c,[0,1]).all()
        return np.arange(len(c),dtype=np.uint32),np.where(c==0,2,1),np.where(c==0,3,5)
    source=DATA/"annotation_data"/row["source"]
    with source.open("rb") as stream:
        for _ in range(64):
            if stream.readline(512).strip()==b"end_header":break
        else:raise ValueError(source)
        ids=np.fromfile(stream,dtype=np.dtype({"names":["i"],"formats":["<u4"],"offsets":[16],"itemsize":20}))["i"].copy()
    assert hashlib.sha256(ids.tobytes()).hexdigest()==row["index_sha256"]
    code=np.zeros(len(ids),np.uint8)
    by_id={int(idx):i for i,idx in enumerate(ids)}
    conflicts=np.zeros(len(ids),bool)
    assigned={}
    label=DATA/"annotation_data"/row["label_path"]
    if row["domain"]=="follow":
        annotations=read(label)["annotations"]
    else:
        annotations=[]
        with label.open("rb") as f:
            for off,length,digest in row["label_spans"]:
                f.seek(off); data=f.read(length)
                assert hashlib.sha256(data).hexdigest()==digest
                annotations.append(json.loads(data))
    for ann in annotations:
        if row["domain"]=="follow":
            name=ann["class_name"]
            instance=ann.get("instance_id","")
        else:
            name=ann["entity_kind"] if ann["label"]=="entity" else ann["label"]
            instance=ann.get("entity_uid","")
        class_index={"person":1,"pedestrian":1,"vehicle":2,"dust":3,"static":4,"static_boundary":4}[name]
        identity=(class_index,instance if class_index<3 else "")
        for idx in ann["point_indices"]:
            pos=by_id[idx]
            if idx in assigned and assigned[idx]!=identity:conflicts[pos]=True
            assigned[idx]=identity
            code[pos]=class_index
    code[conflicts]=0
    return ids,np.choose(code,[0,1,1,2,0]),code


def check_config(run,rows):
    config=read(run/"config.json"); cfg=config["config"]
    assert config["manifest_sha256"]==FROZEN and cfg["size"]>512
    role=lambda r:(r["domain"]=="uchile" and (cfg["scope"]!="pair" or (r["temporal_status"]=="T0" and len(r["history"])>=3))) or (cfg["scope"]=="joint" and r["domain"]=="ped")
    for split,key in (("train","train_uids"),("val","selection_val_uids")):
        assert config[key]==[r["uid"] for r in rows if r["role"]==split and role(r)]
    records=[json.loads(x) for x in (run/"epochs.jsonl").read_text().splitlines()]
    finished=read(run/"finished.json")
    validations=[r for r in records if "validation_macro_AP" in r]
    best=max(validations,key=lambda r:r["validation_macro_AP"])
    assert best["epoch"]==finished["selected_epoch"] and sha(run/"best.pt")==finished["checkpoint_sha"]
    for record in validations:
        assert np.isclose(np.mean([v for v in record["event_AP"].values() if v is not None]),record["validation_macro_AP"])
    paired_epochs=None
    if cfg["model"]=="N1":
        base=run.with_name(run.name.replace("_n1_","_n0_"))
        baseconfig=read(base/"config.json")
        assert config["train_uids"]==baseconfig["train_uids"] and config["selection_val_uids"]==baseconfig["selection_val_uids"] and config["grid_train_only"]==baseconfig["grid_train_only"]
        logs=[json.loads(x) for x in (base/"epochs.jsonl").read_text().splitlines()]
        for one,two in zip(records,logs):
            for item in ("epoch","updates","unique_training_frames","counts_ignore_non_dust_dust","skipped_empty_batches"):assert one[item]==two[item]
        paired_epochs=min(len(logs),len(records))
    return dict(seed=cfg["seed"],model=cfg["model"],scope=cfg["scope"],train_frames=len(config["train_uids"]),selection_val_frames=len(config["selection_val_uids"]),epochs=len(records),updates=sum(r["updates"] for r in records),identical_exposures_common_epochs=paired_epochs,best_epoch=best["epoch"],stored_selection_macro_AP=best["validation_macro_AP"],checkpoint_sha=finished["checkpoint_sha"])


def model_results(files,rows,refs,key,net=False,fallback=None):
    by_event=defaultdict(list)
    counts=Counter()
    frame_support=Counter()
    for row in rows:
        original,code,ref=refs[row["uid"]]
        with np.load(files(row),allow_pickle=False) as data:
            assert np.array_equal(data["original_index"],original) and np.array_equal(data["code"],code) and np.array_equal(data["ref"],ref),row["uid"]
            score=data["score" if net else "score_"+key]
            assert score.shape==original.shape
            if net:
                raw=data["raw_scores"];positive=raw.sum(1)>0
                assert raw.shape==(len(score),2) and np.array_equal(data["predicted_mask"],np.isfinite(score)) and np.array_equal(positive,np.isfinite(score))
                assert np.array_equal(score[positive],(raw[positive,1]/raw.sum(1)[positive]))
                if fallback is not None:
                    missing=~data["temporal_available"]
                    with np.load(fallback/row["role"]/(row["uid"]+".npz"),allow_pickle=False) as other:
                        assert np.array_equal(other["original_index"],original)
                        assert np.array_equal(score[missing],other["score"][missing],equal_nan=True)
                        assert np.array_equal(raw[missing],other["raw_scores"][missing],equal_nan=True)
                    counts.update(fallback=int(missing.sum()))
            else:
                assert str(data["role"])==row["role"] and str(data["uid"])==row["uid"]
                inactive=~data["avail_"+key].astype(bool)&data["valid"].astype(bool)
                assert np.array_equal(score[inactive],data["score_S"][inactive])
            counts.update(rows=len(score),finite=int(np.isfinite(score).sum()),ignored=int((code==0).sum()))
            by_event[(row["role"],row["domain"],row["event"])].append((score,code,ref))
            if row["domain"]=="ped" and row["role"]=="val":
                eligible=(code==1)&np.isfinite(score)
                frame_support.update(person=int((eligible&(ref==1)).any()),vehicle=int((eligible&(ref==2)).any()))
    event_stats={}
    risk_stats={}
    validation=[item for (role,domain,_),items in by_event.items() if role=="val" and domain=="ped" for item in items]
    policy=validation_threshold(validation,frame_support)
    for (role,domain,event),items in by_event.items():
        score,code,ref=(np.concatenate(col) for col in zip(*items))
        valid=np.isfinite(score)&(code>0)
        ap,auc=ranking(score[valid],code[valid]==2)
        event_stats["|".join((role,domain,event))]=dict(ap=ap,trapezoid_pr_auc=auc,**operating(score,code,ref,.5))
        if policy["threshold"] is not None:
            risk_stats["|".join((role,domain,event))]=operating(score,code,ref,policy["threshold"])
    return dict(point_totals=counts,event05=event_stats,policy_oracle=policy,event_risk=risk_stats)


def compare_network_report(audited,report):
    checks=0
    for item in read(report):
        name=item["run"]
        if name not in audited:continue
        event_data=audited[name]["event05"]
        for domain in ("uchile","ped","follow"):
            primary=item["metrics"][domain]
            agents={key.split("|",2)[2]:v for key,v in event_data.items() if key.startswith("test|"+domain+"|")}
            assert set(agents)==set(primary["AP_by_event"])
            for event,actual in agents.items():
                estimate=primary["AP_by_event"][event]
                assert (estimate is None and actual["ap"] is None) or np.isclose(estimate,actual["ap"],atol=2e-12,rtol=0),(name,domain,event)
                checks+=1
            for k in ("tp","fp","fn"):
                assert primary[k.upper()]==sum(v[k] for v in agents.values());checks+=1
            for k,risk in (("person","person_n"),("vehicle","vehicle_n"),("vehicle_fp","vehicle_fp"),("person_fp","person_fp")):
                assert primary["risk"][risk]==sum(v[k] for v in agents.values());checks+=1
    return checks


def check_probe_train(seed,rows,out):
    valid_rows=[r for r in rows if r["role"]=="train"]
    weights=read(out/"weights"/str(seed)/"training.json")
    identity=hashlib.sha256()
    digest=lambda x:int.from_bytes(hashlib.sha256(x.encode()).digest()[:4],"little")
    account=Counter()
    for row,data in zip(valid_rows,weights["training_frames"]):
        uid=row["uid"]
        assert data["uid"]==uid
        idx,code,ref=independent_reference(row)
        legal=np.flatnonzero(code>0)
        pool=np.sort(np.random.default_rng(digest("train-pool/"+uid)).choice(legal,min(len(legal),2048),replace=False))
        selected=pool[np.sort(np.random.default_rng(digest(str(seed)+"/"+uid)).choice(len(pool),min(len(pool),1024),replace=False))]
        identity.update(uid.encode()+b"\0"); identity.update(idx[selected].astype("<i8").tobytes())
        for name,value in (("points",len(selected)),("dust",int((code[selected]==2).sum())),("person",int((ref[selected]==1).sum())),("vehicle",int((ref[selected]==2).sum()))):
            assert data[name]==value; account[name]+=value
    assert len(valid_rows)==len(weights["training_frames"]) and identity.hexdigest()==weights["common_query_sha256"]
    assert account["points"]==weights["training_rows"] and np.isclose(weights["positive_weight"],np.sqrt((account["points"]-account["dust"])/account["dust"]),rtol=2e-7)
    assert all(len(model["epoch_losses"])==weights["epochs"] and np.isfinite(model["epoch_losses"]).all() for model in weights["curves"].values())
    return dict(frames=len(valid_rows),unique_training_query_sha256=identity.hexdigest(),queries=account,epochs=weights["epochs"],class_weight=weights["positive_weight"])


def paired(seed,rows,refs):
    root=RUNS/"temporal_probe_197_r2/scores"/str(seed)
    paths={m:RUNS/f"temporal_randlav1_pair_{m}_{seed}/predictions/test" for m in ("n0","n1")}
    events=defaultdict(lambda:defaultdict(list))
    families=("S","T2","TK","TF","COPY","ACC","MASK","DISTANT","SHUFFLE","TK_F4","TK_REC")
    control_required=("COPY","ACC","MASK","DISTANT","SHUFFLE","TK_F4","TK_REC")
    for row in rows:
        if row["role"]!="test" or row["domain"]!="uchile" or row["temporal_status"]!="T0" or len(row["history"])<3:continue
        fn=row["uid"]+".npz"
        original,code,_=refs[row["uid"]]
        with np.load(root/fn) as payload, np.load(paths["n0"]/fn) as n0, np.load(paths["n1"]/fn) as n1:
            assert all(np.array_equal(original,x["original_index"]) for x in (payload,n0,n1))
            score={model:payload["score_"+model] for model in families}
            score.update(N0=n0["score"],N1=n1["score"])
            base=(code>0)&n1["temporal_available"]
            for family in ("S","T2","TK","TF"):base&=payload["avail_"+family]&np.isfinite(score[family])
            base&=np.isfinite(score["N0"])&np.isfinite(score["N1"])
            block=events[row["event"]]
            block["code"].append(code[base])
            for key in ("S","T2","TK","TF","N0","N1"):block[key].append(score[key][base])
            for key in control_required:
                valid=base&payload["avail_"+key]&np.isfinite(score[key])
                block[key+"_labels"].append(code[valid]);block[key].append(score[key][valid]);block[key+"_TF"].append(score["TF"][valid])
    result={}
    for event,block in events.items():
        y=np.concatenate(block["code"])==2
        result[event]=dict(rows=len(y),dust=int(y.sum()),AP={key:ranking(np.concatenate(block[key]),y)[0] for key in ("S","T2","TK","TF","N0","N1")})
        controls={}
        for key in control_required:
            cy=np.concatenate(block[key+"_labels"])==2
            controls[key]=dict(rows=len(cy),dust=int(cy.sum()),control_AP=ranking(np.concatenate(block[key]),cy)[0],TF_AP=ranking(np.concatenate(block[key+"_TF"]),cy)[0])
        result[event]["matched_controls"]=controls
    return result


def ped_risk(rows,refs,files,field,threshold):
    outputs=[]
    for row in rows:
        if row["domain"]!="ped" or row["role"]!="test":continue
        original,code,ref=refs[row["uid"]]
        by_oid={int(index):position for position,index in enumerate(original)}
        instances=defaultdict(set)
        with (DATA/"annotation_data"/row["label_path"]).open("rb") as f:
            for off,size,digest in row["label_spans"]:
                f.seek(off);line=f.read(size)
                assert hashlib.sha256(line).hexdigest()==digest
                record=json.loads(line)
                if record["label"]=="entity" and record.get("entity_kind") in ("pedestrian","person"):
                    assert record["source_frame_identity"]["frame_uid"]==row["uid"] and record["entity_uid"]
                    instances[record["entity_uid"]].update(pos for key in record["point_indices"] if code[pos:=by_oid[key]]==1 and ref[pos]==1)
        finite=0
        with np.load(files(row)) as z:
            assert np.array_equal(original,z["original_index"])
            score=z[field]
        assert sum(len(ids) for ids in instances.values())==int(((code==1)&(ref==1)).sum())
        for name,points in instances.items():
            if not points:continue
            selected=score[sorted(points)]
            assert np.isfinite(selected).all()
            n=len(selected);loss=int(np.sum(selected>=threshold))
            outputs.append(dict(uid=row["uid"],source_instance=name,reference_points=n,suppressed=loss,retained=n-loss))
    group=lambda sample:dict(instance_frames=len(sample),at_least_one_suppressed=sum(r["suppressed"]>0 for r in sample),half_or_more_suppressed=sum(2*r["suppressed"]>=r["reference_points"] for r in sample),no_points_retained=sum(r["retained"]==0 for r in sample),at_least_one_retained=sum(r["retained"]>0 for r in sample),reference_points=sum(r["reference_points"] for r in sample),suppressed=sum(r["suppressed"] for r in sample))
    return dict(threshold=threshold,scope="within each frame, annotated pedestrian group only, not certified tracks or independent instances",all=group(outputs),min10_reference_points=group([r for r in outputs if r["reference_points"]>=10]),source_cases=outputs)


def compare_main(results,folder):
    comparisons={}
    for directory in sorted(folder.glob("[0-9]*")):
        if not (directory/"metrics.csv").is_file():continue
        seed=directory.name
        oracle={key.split("/")[1]:value for key,value in results["probes"].items() if key.startswith(seed+"/")}
        for name,value in results["networks"].items():
            if name.endswith("_"+seed):
                scope,net=name.split("_")[-3:-1]
                oracle[net.upper()+"_"+scope]=value
        matched=results.get("paired",{}).get(seed,{})
        checks=Counter()
        same=lambda actual,expected: (actual in (None,"") if expected is None else np.isclose(float(actual),expected,atol=2e-12,rtol=0))
        for name,policy in read(directory/"policies.json").items():
            if name not in oracle:continue
            expected=oracle[name]["policy_oracle"]
            assert same(policy["threshold"],expected["threshold"]) and same(policy["maximum_budget_recall"],expected["max_budget_recall"]),(seed,name,policy,expected)
            for field,expected_field in [("val_person","person"),("val_vehicle","vehicle"),("val_dust","dust")]:assert policy[field]==expected[expected_field]
            assert policy["person_frames"]==expected["support_frames"]["person"] and policy["vehicle_frames"]==expected["support_frames"]["vehicle"]
            checks["policies"]+=1
        with (directory/"metrics.csv").open() as stream:
            for row in csv.DictReader(stream):
                model=row["model"];event=row["event"]
                if row["policy"]!="fixed" or event=="ALL":continue
                if model in oracle and row["scope"]=="all":
                    path="test|"+row["domain"]+"|"+event
                    item=oracle[model]["event05"][path]
                    assert same(row["AP"],item["ap"]) and same(row["PR_AUC"],item["trapezoid_pr_auc"]),(seed,model,event)
                    for source,target in (("tp","tp"),("fp","fp"),("fn","fn"),("tn","tn"),("person_den","person"),("vehicle_den","vehicle"),("person_fp","person_fp"),("vehicle_fp","vehicle_fp"),("ignore_candidates","ignored_candidate")):
                        assert int(row[source])==item[target],(seed,model,event,source)
                    checks["full_event_rows"]+=1
                if row["scope"]=="matched" and event in matched:
                    key={"N0_pair":"N0","N1_pair":"N1"}.get(model,model)
                    if key in matched[event]["AP"]:
                        assert same(row["AP"],matched[event]["AP"][key]) and int(row["labelled_scored"])==matched[event]["rows"],(seed,model,event)
                        checks["matched_event_rows"]+=1
        with (directory/"matched_controls.csv").open() as stream:
            for row in csv.DictReader(stream):
                if row["scope"]!="matched" or row["event"] not in matched:continue
                item=matched[row["event"]]["matched_controls"].get(row["control"])
                if item is None:continue
                assert int(row["rows"])==item["rows"] and int(row["dust"])==item["dust"]
                assert same(row["AP_control"],item["control_AP"]) and same(row["AP_TF"],item["TF_AP"]),(seed,row["control"],row["event"])
                checks["control_event_rows"]+=1
        comparisons[seed]=dict(verified=checks,source_sha256={file:sha(directory/file) for file in ("metrics.csv","policies.json","matched_controls.csv")})
    return comparisons


def stratified_check(rows,refs,folder):
    shared=RUNS/"temporal_probe_197_r2/scores/197"
    totals=defaultdict(Counter)
    vox=lambda xx,scale: np.ascontiguousarray(np.floor(np.asanyarray(xx,np.float64)/scale).astype(np.int32)).view("V12").ravel()
    @lru_cache(maxsize=24)
    def prior(source):
        xx=np.load(DATA/"dataset_polvo"/source/"coord.npy").astype(np.float32).astype(np.float64)
        return np.unique(vox(xx,.1)),np.unique(vox(xx,.6)),xx.min(0),xx.max(0)
    for row in rows:
        if row["role"]!="test":continue
        uid=row["uid"]
        ix,code,ref=refs[uid]
        if row["domain"]=="uchile":
            xyz=np.load(DATA/"dataset_polvo"/row["source"]/"coord.npy").astype(np.float32)
        else:
            path=DATA/"annotation_data"/row["source"]
            with path.open("rb") as stream:
                while stream.readline(256).strip()!=b"end_header":pass
                raw=np.fromfile(stream,"<f4").reshape(-1,5)
            xyz=raw[:,:3].copy()
        fine=vox(xyz,.1);region=vox(xyz,.6)
        _,inv,counts=np.unique(fine,return_counts=True,return_inverse=True)
        density=counts[inv]
        history=row["history"]
        n_seen=np.zeros(len(code),np.int16);n_hit=n_seen.copy()
        last_lo=last_hi=None
        for descriptor in history:
            old,coarse,lo,hi=prior(descriptor["source"])
            seen=np.isin(region,coarse)&((xyz>=lo-.1)&(xyz<=hi+.1)).all(1)
            n_seen+=seen;n_hit+=seen&np.isin(fine,old)
            last_lo,last_hi=lo,hi
        persistent=(n_seen>=3)&(3*n_hit>=2*n_seen)
        distance=np.linalg.norm(xyz,axis=1)
        edges=[0,1,2,4,8,np.inf] if row["domain"]=="uchile" else [0,8,16,32,np.inf]
        groups={f"range_{a}_{b}":(distance>=a)&(distance<b) for a,b in zip(edges,edges[1:])}
        groups["sparse_non_dust_proxy"]=(density<=2)&(code==1)
        groups["dense_persistent_dust"]=(density>=8)&persistent&(code==2)
        with np.load(shared/(uid+".npz")) as data:
            assert np.array_equal(data["original_index"],ix)
            expected=data["visibility"]
            if history:
                outside=((xyz<last_lo-.1)|(xyz>last_hi+.1)).any(1)
                assert np.array_equal(expected==1,outside&~data["available"])
                assert np.array_equal(expected==4,~outside&~data["available"])
            else:
                assert ((expected==2)|(expected==3)).all()
            groups["out_of_support"]=expected==1
            groups["ambiguous_visibility"]=expected==4
            groups["no_history_or_pose"]=np.isin(expected,[2,3])
            for name in ("S","TF"):
                s=data["score_"+name]
                for key,mask in groups.items():
                    totals[(row["domain"],name,key)].update(operating(s[mask],code[mask],ref[mask],.5),rows=int(mask.sum()))
    checked=0
    for row in csv.DictReader((folder/"197/strata.csv").open()):
        if row["policy"]!="fixed":continue
        got=totals.get((row["domain"],row["model"],row["stratum"]))
        if got is None:continue
        for origin,target in [("tp","tp"),("fp","fp"),("fn","fn"),("tn","tn"),("rows","rows"),("vehicle_den","vehicle"),("person_den","person"),("ignore_candidates","ignored_candidate")]:
            assert int(row[origin])==got[target],(row["domain"],row["model"],row["stratum"],origin,int(row[origin]),got[target])
        checked+=1
    assert checked==len(totals)
    return dict(seed=197,models=["S","TF"],stratum_rows=checked,checks="complete test spatial masks, range, counts, multi-frame persistence, saved visibility and denominators")


def all_frontiers(rows,refs,folder):
    selected=[r for r in rows if r["domain"]=="ped" and r["role"]=="val"]
    output={}
    for seed_dir in sorted(folder.glob("[0-9]*")):
        if not (seed_dir/"policies.json").is_file():continue
        seed=seed_dir.name
        policies=read(seed_dir/"policies.json")
        groups=defaultdict(list);frame_support=Counter()
        for row in selected:
            ix,code,ref=refs[row["uid"]]
            filename=row["uid"]+".npz"
            frame_support.update(person=int((ref==1).any()),vehicle=int((ref==2).any()))
            with np.load(RUNS/"temporal_probe_197_r2/scores"/seed/filename) as probe:
                assert np.array_equal(probe["original_index"],ix)
                for key in policies:
                    if key.startswith(("N0_","N1_")):
                        model,scope=key.lower().split("_",1)
                        pred=RUNS/f"temporal_randlav1_{scope}_{model}_{seed}/predictions/val"/filename
                        with np.load(pred) as arr:
                            assert np.array_equal(arr["original_index"],ix)
                            s=arr["score"]
                    else:s=probe["score_"+key]
                    groups[key].append((s,code,ref))
        counts={}
        for key,items in groups.items():
            s,c,r=(np.concatenate(col) for col in zip(*items))
            ok=np.isfinite(s)&(c>0)
            with np.load(seed_dir/(key+"_validation_curve.npz")) as curve:
                t=curve["threshold"]
                assert np.array_equal(t,np.unique(s[ok])[::-1]),(seed,key,"candidates")
                for col,mask in [("dust_tp",c==2),("person_fp",(r==1)&(c==1)),("vehicle_fp",(r==2)&(c==1))]:
                    eligible=s[ok&mask]
                    expected=len(eligible)-np.searchsorted(np.sort(eligible),t,side="left")
                    assert np.array_equal(curve[col],expected),(seed,key,col)
            chosen=validation_threshold(items,frame_support); p=policies[key]
            assert p["threshold"]==chosen["threshold"] and np.isclose(p["maximum_budget_recall"],chosen["max_budget_recall"],atol=1e-15,rtol=0)
            counts[key]=len(t)
        output[seed]=counts
    return output


def rviz_cases(rows):
    root=PROJECT/"temporal_open3d_v1/rviz_197"
    receipt=read(root/"verified/verified.json")
    table=list(csv.DictReader((root/"verified/errors_original_index.csv").open()))
    rows_by_uid={r["uid"]:r for r in rows}
    for case in receipt["case_results"]:
        uid=case["uid"];row=rows_by_uid[uid]
        ix,code,ref=independent_reference(row)
        if row["domain"]=="uchile":
            original=DATA/"dataset_polvo"/row["source"]
            xyz=np.load(original/"coord.npy").astype(np.float32);intensity=np.load(original/"intensity.npy")
        else:
            with (DATA/"annotation_data"/row["source"]).open("rb") as f:
                for _ in range(64):
                    if f.readline(512).strip()==b"end_header":break
                else:raise ValueError("PLY")
                buffer=np.fromfile(f,"<f4").reshape(-1,5)
            xyz=buffer[:,:3];intensity=buffer[:,3]
        with np.load(RUNS/"temporal_probe_197_r2/scores/197"/(uid+".npz")) as scores:
            assert np.array_equal(scores["original_index"],ix)
            for model in ("S","TF"):
                s=scores["score_"+model]
                error=np.isfinite(s)&(code>0)&((s>=.5)!=(code==2))
                source_rows=np.flatnonzero(error);logged=[a for a in table if a["uid"]==uid and a["method"]==model]
                assert len(logged)==len(source_rows)
                expected={int(ix[index]):index for index in source_rows}
                for a in logged:
                    j=expected.pop(int(a["original_index"]))
                    assert int(a["source_ref"])==ref[j] and float(a["score"])==s[j]
                    assert a["error"]==("FN" if code[j]==2 else "FP")
                    assert np.array_equal([float(a[k]) for k in ("x","y","z")],xyz[j]) and float(a["intensity"])==intensity[j]
                assert not expected
    assert len(table)==receipt["error_rows"]
    return dict(errors=len(table),cases=len(receipt["case_results"]),wire_records_read=receipt["wire"],tty_receipt=receipt["tty"],actual_autoplay_advances=receipt["autoplay"],receipt_sha=sha(root/"verified/verified.json"),screenshot_contact_sha=sha(root/"verified/contact.png"))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--net",nargs="*",default=[])
    parser.add_argument("--probe",nargs="*",type=int,default=[])
    parser.add_argument("--probe-models",nargs="+",default=["S","T2","TK","TF"])
    parser.add_argument("--network-report",type=Path)
    parser.add_argument("--paired",nargs="*",type=int,default=[])
    parser.add_argument("--metrics-folder",type=Path)
    parser.add_argument("--ped-groups",action="store_true")
    parser.add_argument("--spatial",action="store_true")
    parser.add_argument("--frontiers",action="store_true")
    parser.add_argument("--rviz",action="store_true")
    opt=parser.parse_args()
    rows=read(MB)["frames"]
    results=read(opt.output) if opt.output.exists() else {}
    results["preflight"]=validate_preflight(rows)
    eval_rows=[r for r in rows if r["role"]!="train"]
    results.setdefault("networks",{});results.setdefault("probes",{})
    if opt.net or opt.probe or opt.paired or opt.ped_groups or opt.spatial or opt.frontiers:
        refs={row["uid"]:independent_reference(row) for row in eval_rows}
        results.update(verified_reference_rows=int(sum(len(ix) for ix,_,_ in refs.values())),verified_reference_frames=len(refs))
        for name in opt.net:
            run=RUNS/name
            fallback=RUNS/name.replace("_n1_","_n0_")/"predictions" if "_n1_" in name else None
            results["networks"][name]=dict(training=check_config(run,rows),**model_results(lambda r:run/"predictions"/r["role"]/(r["uid"]+".npz"),eval_rows,refs,"",net=True,fallback=fallback))
        for seed in opt.probe:
            run=RUNS/"temporal_probe_197_r2"
            results.setdefault("probe_training",{})[str(seed)]=check_probe_train(seed,rows,run)
            for key in opt.probe_models:
                results["probes"][str(seed)+"/"+key]=model_results(lambda r:run/"scores"/str(seed)/(r["uid"]+".npz"),eval_rows,refs,key)
        if opt.paired:
            dest=results.setdefault("paired",{})
            for seed in opt.paired:dest[str(seed)]=paired(seed,rows,refs)
        if opt.ped_groups:
            dest=results.setdefault("ped_source_groups",{})
            for name in ("S","TF","N0_pair","N1_pair","N0_joint"):
                if name in ("S","TF"):
                    path=RUNS/"temporal_probe_197_r2/scores/197"
                    files=lambda row:path/(row["uid"]+".npz"); field="score_"+name
                else:
                    net,scope=name.lower().split("_")
                    path=RUNS/f"temporal_randlav1_{scope}_{net}_197/predictions/test"
                    files=lambda row:path/(row["uid"]+".npz");field="score"
                dest[name+"_197"]=ped_risk(rows,refs,files,field,.5)
        if opt.spatial:
            assert opt.metrics_folder
            results["spatial"]=stratified_check(rows,refs,opt.metrics_folder)
        if opt.frontiers:
            assert opt.metrics_folder
            results["exact_validation_frontier_sizes"]=all_frontiers(rows,refs,opt.metrics_folder)
    if opt.network_report:
        results["network_report_comparison"]=dict(source_sha256=sha(opt.network_report),checks=compare_network_report(results["networks"],opt.network_report))
    if opt.metrics_folder:
        results["primary_report_comparison"]=compare_main(results,opt.metrics_folder)
    if opt.rviz:
        results["rviz"]=rviz_cases(rows)
    pending=opt.output.with_suffix(".partial")
    pending.write_text(json.dumps(results,allow_nan=False,indent=2)+"\n")
    pending.replace(opt.output)
    print("QA results",opt.output,"preflight",results["preflight"]["original_rows_probe"],"networks",len(results["networks"]),"probe configs",len(results["probes"]))


if __name__=="__main__":main()
