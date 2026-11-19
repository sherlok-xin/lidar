"""Full-frame outcome accounting restricted to frozen neural run paths."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np
from sklearn.metrics import average_precision_score
from data_protocol import read_manifest, load_frame


def reduce(groups):
    outputs={}
    for scope,events in groups.items():
        tpfpfn=np.zeros(3,np.int64);risk=Counter();aps={};coverage=Counter()
        for event,records in events.items():
            scores=np.concatenate([entry[0] for entry in records])
            code=np.concatenate([entry[1] for entry in records]);ref=np.concatenate([entry[2] for entry in records])
            ok=np.isfinite(scores);valid=ok & (code!=0);pred=ok & (scores>=.5)
            coverage.update(rows=len(code),scores=int(ok.sum()),labeled=int((code>0).sum()),valid_labeled=int(valid.sum()))
            tpfpfn+=np.array([(pred & (code==2)).sum(),(pred & (code==1)).sum(),(~pred & (code==2)&ok).sum()])
            aps[event]=float(average_precision_score(code[valid]==2,scores[valid])) if (code[valid]==2).any() else None
            for key,c in (("person",1),("vehicle",2)):
                numerator=int(((code==1) & (ref==c) & pred).sum())
                denominator=int(((code==1)&(ref==c)&ok).sum())
                risk.update({key+"_fp":numerator,key+"_n":denominator})
        tp,fp,fn=map(int,tpfpfn);supported=[v for v in aps.values() if v is not None]
        outputs[scope]=dict(coverage=coverage,TP=tp,FP=fp,FN=fn,F1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
                            macro_AP=float(np.mean(supported)) if supported else None,AP_by_event=aps,risk=risk)
    return outputs


def audit(run,rows):
    if not (run/"finished.json").is_file():return None
    freeze=json.loads((run/"config.json").read_text());fin=json.loads((run/"finished.json").read_text())
    if hashlib.sha256((run/"best.pt").read_bytes()).hexdigest()!=fin["checkpoint_sha"]:raise RuntimeError("checkpoint changed")
    checks=0;groups=defaultdict(lambda:defaultdict(list))
    for row in rows:
        if row["role"]!="test":continue
        with np.load(run/"predictions/test"/(row["uid"]+".npz")) as pred:
            idx,code,ref,score,raw,mask=[pred[k] for k in ("original_index","code","ref","score","raw_scores","predicted_mask")]
            if checks<3 or (row["domain"]!="uchile" and checks<45):
                source=load_frame(row)
                for a,b in ((idx,source["original_index"]),(ref,source["ref"]),(code,source["code"])):
                    np.testing.assert_array_equal(a,b)
            norm=np.full(len(score),np.nan,np.float32)
            mass=raw.sum(1);norm[mass>0]=raw[mass>0,1]/mass[mass>0]
            np.testing.assert_array_equal(score,norm);np.testing.assert_array_equal(mask,np.isfinite(score))
            record=(score,code,ref)
            groups[row["domain"]][row["event"]].append(record)
            if row["temporal_status"]=="T0" and len(row["history"])>=3:
                groups["pair_frames"][row["event"]].append(record)
                corresponding=run.parent/f"temporal_randlav1_pair_n1_{freeze['config']['seed']}"/"predictions/test"/(row["uid"]+".npz")
                if corresponding.exists():
                    with np.load(corresponding) as temporal:
                        np.testing.assert_array_equal(idx,temporal["original_index"])
                        comparable=temporal["temporal_available"] & temporal["predicted_mask"] & mask
                    groups["pair_rows"][row["event"]].append(tuple(array[comparable] for array in record))
            checks+=1
    return dict(run=run.name,selection_epoch=fin["selected_epoch"],timing=fin["total_seconds"],gpu=fin["gpu"],
                epochs=len((run/"epochs.jsonl").read_text().splitlines()),eval_frames=checks,metrics=reduce(groups))


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--runs",type=Path,required=True)
    parser.add_argument("--manifest",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();data=read_manifest(args.manifest)
    result=[r for run in sorted(args.runs.glob("temporal_randlav1_*")) if (r:=audit(run,data["frames"])) is not None]
    args.output.write_text(json.dumps(result,indent=2))
