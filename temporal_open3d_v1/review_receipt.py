"""Read back saved case identities, strict wire receipts and OGRE pixels without starting ROS."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from rviz_review import LAYERS,clouds,load_case,sha


def build(book,check,report):
    report.mkdir(exist_ok=False,parents=True)
    metas=json.loads(book.read_text())["cases"]
    wire=json.loads((check/"wire.json").read_text())
    if not wire["complete"] or wire["count"]!=len(metas)*len(LAYERS) or not wire["port_free_after"]:
        raise ValueError("incomplete source, wire, or owned master evidence")
    events=[json.loads(line) for line in (check/"controls.jsonl").read_text().splitlines()]
    commands=[r["input"] for r in events if r["event"]=="command"]
    auto=sum(r.get("reason")=="autoplay" for r in events)
    if not (any(r.get("tty") is True for r in events) and any(r.get("joined") is True for r in events)
            and auto>=1 and set(("n","p","rate 3","play","pause","status","seq 3","q"))<=set(commands)):
        raise ValueError("TTY/automatic advance/commands/close not evidenced")
    evidence=[];errors=[];pictures=[]
    for meta in metas:
        current=load_case(book,meta)
        all_clouds=clouds(current)
        for actual in (row for row in wire["wire"] if row["case"]==meta["case"]):
            expected=all_clouds[actual["layer"]]
            if len(expected)!=actual["width"] or hashlib.sha256(expected.tobytes()).hexdigest()!=actual["sha256"]:
                raise ValueError("wire-source mismatch")
        path=check/("case_"+str(meta["case"]))
        camera=json.loads((path/"capture.json").read_text())
        if not camera["pass_checks"] or len({json.dumps(x["camera"],sort_keys=True) for x in camera["rows"]})!=1:
            raise ValueError("fixed-camera evidence missing")
        for shot in camera["rows"]:
            target=path/(shot["layer"]+".png")
            if sha(target)!=shot["sha256"] or shot["source"]!=meta["uid"] or shot["fixed_frame"]!=meta["frame_id"]:
                raise ValueError("camera/source hash mismatch")
        factors=[]
        for tag in ("S","TF"):
            score=current["score_"+tag]
            miss=np.flatnonzero(current["valid"] & np.isfinite(score) &
                 (((current["code"]==1)&(score>=.5))|((current["code"]==2)&(score<.5))))
            for index in miss:
                errors.append(dict(case=meta["case"],uid=meta["uid"],method=tag,source_ref=int(current["ref"][index]),
                    original_index=int(current["original_index"][index]),error="FP" if current["code"][index]==1 else "FN",
                    x=float(current["xyz"][index,0]),y=float(current["xyz"][index,1]),z=float(current["xyz"][index,2]),
                    intensity=float(current["intensity"][index]),score=float(score[index]),
                    temporal_available=bool(current["available"][index]),stamp=meta["stamp"]))
            factors.append(dict(method=tag,error_points=len(miss),person=int((current["ref"]==1).sum()),
                person_fp=int(((current["ref"]==1)&(score>=.5)).sum()),vehicle=int((current["ref"]==2).sum()),
                vehicle_fp=int(((current["ref"]==2)&(score>=.5)).sum())))
        evidence.append(dict(case=meta["case"],uid=meta["uid"],groups=factors,unavailable=len(all_clouds["unavailable"]),
                unpredicted=len(all_clouds["unpredicted"]),history_display_points=len(all_clouds["past_context"]),
                input_points=meta["original_points"],screenshots=len(camera["rows"])))
        for name in ("raw","reference","temporal","temporal_error"):
            pictures.append((meta,name,Image.open(path/(name+".png")).convert("RGB")))
    if errors:
        with (report/"errors_original_index.csv").open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(errors[0]));writer.writeheader();writer.writerows(errors)
    board=Image.new("RGB",(4*320,3*234),"#101018");draw=ImageDraw.Draw(board)
    for index,(meta,name,image) in enumerate(pictures):
        image.thumbnail((320,210))
        x=(index%4)*320;y=(index//4)*234
        board.paste(image,(x,y));draw.text((x+4,y+210),"case %d | %s"%(meta["case"],name),fill="#f0f0f0")
    board.save(report/"contact.png")
    (report/"verified.json").write_text(json.dumps(dict(wire=wire["count"],tty=True,autoplay=auto,
              inputs=commands,case_results=evidence,error_rows=len(errors),scope="0.5 diagnostic; source-specific, post hoc rendering, no material certification"),indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for arg in ("book","check","out"):parser.add_argument("--"+arg,required=True,type=Path)
    args=parser.parse_args();build(args.book,args.check,args.out)
