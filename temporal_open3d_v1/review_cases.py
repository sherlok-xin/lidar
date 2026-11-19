"""Freeze a small identity-keyed casebook; inference and threshold fitting are not performed."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from data_protocol import load_frame
from temporal import Observation,columns,histories


CASE_UIDS=("interior1__Area_6__amtc_071","exterior2__Area_5__amtc_063")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make(manifest,scores,output):
    raw=json.loads(manifest.read_text())
    rows={r["uid"]:r for r in raw["frames"]}
    for uid in CASE_UIDS:
        if not (scores/(uid+".npz")).is_file():
            raise FileNotFoundError("await actual inference file: "+uid)
    output.mkdir(parents=True,exist_ok=False)
    cases=[]
    for case,uid in enumerate(CASE_UIDS,1):
        row=rows[uid]
        if row["role"]!="test" or row["domain"] not in ("uchile","ped"):
            raise ValueError("case domain/role")
        current=load_frame(row)
        path=scores/(uid+".npz")
        with np.load(path,allow_pickle=False) as prediction:
            if str(prediction["uid"])!=uid or str(prediction["role"])!=row["role"] or str(prediction["event"])!=row["event"]:
                raise ValueError("saved frame identity")
            for name in ("original_index","code","ref","valid"):
                np.testing.assert_array_equal(current[name],prediction[name])
            arrays={key:current[key] for key in ("xyz","intensity","original_index","code","ref","valid")}
            arrays.update({key:prediction[key] for key in ("score_S","score_TF","available","visibility")})
        descriptors=row["history"][-9:]
        if descriptors and (row["domain"]!="uchile" or row["temporal_status"]!="T0"):
            raise ValueError("history outside public static mining protocol")
        past=[load_frame(item,labels=False) for item in descriptors]
        arrays["features"]=np.zeros((len(current["xyz"]),8),np.float32)
        arrays["module_available"]=np.zeros((len(current["xyz"]),3),bool)
        if past:
            obs=Observation(current)
            features=histories(obs,obs.xyz,obs.intensity,[Observation(h) for h in past])
            arrays["features"][current["valid"]]=columns(features["F0"][:,3],features["F1"][:,0],features["F1"][:,1],
                features["F2"][:,1],features["F3"][:,4],features["F4"][:,2],features["REC"][:,0],features["MASK"][:,0])
            arrays["module_available"][current["valid"]]=columns(features["F2"][:,-1],features["F3"][:,-1],features["F4"][:,-1]).astype(bool)
        np.testing.assert_array_equal(arrays["features"][:,7]>0,arrays["available"])
        if not past:
            np.testing.assert_array_equal(arrays["score_S"],arrays["score_TF"])
        history=[[],[],[],[]]
        for item,desc in zip(past,descriptors):
            valid=np.flatnonzero(item["valid"])
            sample=valid[np.linspace(0,len(valid)-1,min(1536,len(valid)),dtype=int)]
            for destination,values in zip(history,[item["xyz"][sample],item["intensity"][sample],
                    item["original_index"][sample],np.full(len(sample),row["ordinal"]-desc["ordinal"],np.uint8)]):
                destination.append(values)
        for values,name in zip(history,("history_xyz","history_intensity","history_index","history_lag")):
            arrays[name]=np.concatenate(values) if values else np.empty((0,3) if name=="history_xyz" else (0,),
                dtype=np.uint32 if name=="history_index" else np.uint8 if name=="history_lag" else np.float32)
        filename="case_%d.npz"%case
        np.savez_compressed(output/filename,**arrays)
        xyz=current["xyz"][current["valid"]]
        lo,hi=np.quantile(xyz,[.05,.95],axis=0)
        center=(lo+hi)/2
        cases.append(dict(case=case,uid=uid,event=row["event"],role=row["role"],domain=row["domain"],
                ordinal=row["ordinal"],source=row["source"],frame_id=row["frame_id"],stamp=row["sensor_stamp_ns"],
                time_status=row["time_status"],history_uids=[item["uid"] for item in descriptors],
                history_ordinals=[item["ordinal"] for item in descriptors],
                label_source=row["label_source"],identity="input NPY row or POST-LIO original_index",
                original_points=len(current["xyz"]),valid=int(current["valid"].sum()),
                threshold=0.5,operating_point="fixed diagnostic, not risk policy",
                file=filename,artifact_sha256=digest(output/filename),score_sha256=digest(path),
                view=dict(center=center.tolist(),distance=max(1,float(np.linalg.norm(hi-lo)*1.55)),yaw=.78,pitch=.4)))
    book=dict(manifest_sha256=digest(manifest),cases=cases,
              method="min sha256('rviz-v1/'+UID) per eligible interior, exterior and pedestrian test stratum; fixed before scores; not chronological navigation")
    (output/"cases.json").write_text(json.dumps(book,indent=2))
    return book


if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("--manifest",required=True,type=Path)
    cli.add_argument("--scores",required=True,type=Path)
    cli.add_argument("--out",required=True,type=Path)
    args=cli.parse_args()
    print(json.dumps(make(args.manifest,args.scores,args.out),indent=2))
