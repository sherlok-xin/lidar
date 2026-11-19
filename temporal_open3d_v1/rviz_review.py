"""Noetic review of precomputed source-identity-checked cases, isolated loopback ROS only."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np

MASTER="http://127.0.0.1:11439"
BASE="/mining_temporal_review/"
LAYERS=("raw","reference","single","temporal","single_error","temporal_error","unavailable",
        "unpredicted","stable_core","translation_residual","smoothing_gain","past_context")
CURRENT=(0x38C9B9,0xFF993C)
DTYPE=np.dtype([("x","<f4"),("y","<f4"),("z","<f4"),("intensity","<f4"),("rgb","<u4"),
    ("original_index","<u4"),("score_s","<f4"),("score_tf","<f4"),("evidence","<f4"),
    ("source_ref","u1"),("temporal_available","u1"),("history_lag","u1"),("predicted","u1")])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def schema():
    types={"f":7,"u":6}
    return [dict(name=name,offset=DTYPE.fields[name][1],datatype=2 if DTYPE[name].itemsize==1 else
                 types[DTYPE[name].kind],count=1) for name in DTYPE.names]


def controls():
    path=Path(__file__).with_name("playback_controls.py")
    spec=importlib.util.spec_from_file_location("read_only_controller",str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def guard():
    if os.environ.get("ROS_MASTER_URI")!=MASTER or os.environ.get("ROS_IP")!="127.0.0.1" or os.environ.get("ROS_HOSTNAME") not in (None,"","localhost","127.0.0.1"):
        raise ValueError("use dedicated loopback :11439")


def load_case(book,meta):
    path=Path(book).parent/meta["file"]
    if sha(path)!=meta["artifact_sha256"]:
        raise ValueError("case payload hash mismatch")
    with np.load(path,allow_pickle=False) as src:
        return dict(src)


def clouds(case):
    valid=case["valid"].astype(bool)
    xyz=case["xyz"][valid]
    ref=case["ref"][valid]
    code=case["code"][valid]
    feat=case["features"][valid]
    available=case["available"][valid].astype(bool)
    s=case["score_S"][valid]
    tf=case["score_TF"][valid]
    common=np.zeros(len(xyz),DTYPE)
    for name,v in zip(("x","y","z"),xyz.T): common[name]=v
    common["intensity"]=case["intensity"][valid]
    common["original_index"]=case["original_index"][valid]
    common["source_ref"]=ref
    common["temporal_available"]=available
    common["score_s"]=s;common["score_tf"]=tf
    common["predicted"]=np.isfinite(s)&np.isfinite(tf)
    common["evidence"]=np.nan
    def layer(mask,color,evidence=None):
        seg=common[mask].copy()
        seg["rgb"]=np.broadcast_to(color,(len(common),))[mask]
        if evidence is not None: seg["evidence"]=evidence[mask]
        return seg
    all_points=np.ones(len(common),bool)
    color_for=lambda value:np.where(np.isfinite(value),np.where(value>=.5,CURRENT[1],CURRENT[0]),0x777777)
    intensity=np.arcsinh(common["intensity"])
    low,high=(np.quantile(intensity,[.03,.97]) if len(intensity) else (0,1))
    gray=(42+np.clip((intensity-low)/max(1e-8,high-low),0,1)*205).astype(np.uint32)
    out={"raw":layer(all_points,gray*0x010101),
         "reference":layer(all_points,np.where(code==2,CURRENT[1],np.where(code==1,CURRENT[0],0x67676D))),
         "single":layer(all_points,color_for(s)),"temporal":layer(all_points,color_for(tf)),
         "unavailable":layer(~available,0xAC72E4),"unpredicted":layer(~common["predicted"].astype(bool),0xDDDDDD)}
    for key,value in (("single_error",s),("temporal_error",tf)):
        fp=(code==1)&(value>=.5)
        fn=(code==2)&(value<.5)
        out[key]=layer(np.isfinite(value)&(fp|fn),np.where(fp,0xFF3849,0x4373FF))
    for name,index,limit,maskcol in (("stable_core",4,1.,1),("translation_residual",3,.20,0),("smoothing_gain",5,.1,2)):
        val=feat[:,index]
        frac=np.clip(np.abs(val)/limit,0,1)
        strong=(55+200*frac).astype(np.uint32)
        tint=np.where(val>=0,(strong<<16)|(78<<8)|40,(48<<16)|(90<<8)|strong)
        out[name]=layer(available & case["module_available"][valid,maskcol],tint,val)
    histxyz=case["history_xyz"]
    hist=np.zeros(len(histxyz),DTYPE)
    for name,value in zip(("x","y","z"),histxyz.T): hist[name]=value
    hist["intensity"]=case["history_intensity"];hist["original_index"]=case["history_index"]
    hist["history_lag"]=case["history_lag"];hist["score_s"]=hist["score_tf"]=hist["evidence"]=np.nan
    hist["rgb"]=0x284B00+np.maximum(30,220-18*hist["history_lag"].astype(int))
    out["past_context"]=hist
    return out


def as_message(points,meta):
    import rospy
    from sensor_msgs.msg import PointCloud2,PointField
    from std_msgs.msg import Header
    stamp=meta["stamp"] or 0
    message=PointCloud2()
    message.header=Header(seq=meta["case"],stamp=rospy.Time(stamp//10**9,stamp%10**9),frame_id=meta["frame_id"])
    message.height=1;message.width=len(points);message.fields=[PointField(**info) for info in schema()]
    message.is_dense=True;message.is_bigendian=False;message.point_step=DTYPE.itemsize
    message.row_step=message.width*message.point_step;message.data=points.tobytes()
    return message


def play(args):
    import rospy
    import signal
    from sensor_msgs.msg import PointCloud2
    from std_msgs.msg import String
    ctl=controls()
    frames=[dict(seq=m["case"],meta=m) for m in json.loads(args.book.read_text())["cases"]]
    rospy.init_node("mining_case_review",anonymous=True,disable_signals=True,log_level=rospy.WARN)
    publishers={key:rospy.Publisher(BASE+key,PointCloud2,queue_size=1,latch=True) for key in LAYERS}
    identity=rospy.Publisher(BASE+"source",String,queue_size=1,latch=True)
    logger=ctl.AsyncLog(args.log);console=ctl.Console();previous=[None,None]
    def send(index,reason):
        meta=frames[index]["meta"]
        if previous[0]!=index:
            data=clouds(load_case(args.book,meta))
            previous[:]=[index,{name:ctl.engine.source_header_message(as_message(data[name],meta)) for name in LAYERS}]
        for name,message in previous[1].items(): publishers[name].publish(message)
        identity.publish(String(data=json.dumps(meta)))
        logger.event("frame",seq=meta["case"],uid=meta["uid"],reason=reason,stamp=meta["stamp"])
    session=ctl.Playback(frames,send,logger.event,args.case,args.rate,2.,False)
    reader=ctl.InputLines(sys.stdin)
    try:
        signal.signal(signal.SIGTERM,lambda *unused:session.stop())
        session.start();logger.event("startup",tty=reader.is_tty)
        console.say("Source cases, not a continuous acquisition. n/p/seq N/play/pause/rate X/status/q + Enter.")
        while not rospy.is_shutdown() and not session.stopped:
            if session.error or logger.error: raise RuntimeError(str(session.error or logger.error))
            for line in reader.poll(.03):
                try: action,state=session.command(line)
                except (ValueError,KeyError) as error:
                    console.say(str(error));continue
                console.say(action+" "+json.dumps(state))
                logger.event("command",input=line,action=action,**state)
            if reader.eof:break
    finally:
        session.stop();joined=session.join();logger.event("closed",joined=joined)
        rospy.signal_shutdown("review ended")
        logger.close();console.close()
        if not joined: raise RuntimeError("publisher not joined")


def view(args):
    from PyQt5 import QtCore,QtWidgets
    from rviz import bindings as rviz
    from PIL import Image
    import rospy
    from std_msgs.msg import String
    rospy.init_node("mining_rviz_identity",anonymous=True,disable_signals=True,log_level=rospy.WARN)
    meta=next(m for m in json.loads(args.book.read_text())["cases"] if m["case"]==args.case)
    application=QtWidgets.QApplication([])
    window=QtWidgets.QWidget()
    window.setWindowTitle("Mining LiDAR: publisher labels / SOURCE_LABEL_PROXY")
    layout=QtWidgets.QVBoxLayout(window);notice=QtWidgets.QLabel();layout.addWidget(notice)
    tools=QtWidgets.QHBoxLayout();combo=QtWidgets.QComboBox();combo.addItems(LAYERS)
    history_box=QtWidgets.QCheckBox("overlay past (separate observed returns)");tools.addWidget(combo);tools.addWidget(history_box);layout.addLayout(tools)
    visual=rviz.VisualizationFrame();visual.setSplashPath("");visual.initialize(str(Path(__file__).resolve().parent/"view.rviz"));visual.setMenuBar(None);visual.setStatusBar(None)
    layout.addWidget(visual);manager=visual.getManager()
    group=manager.getRootDisplayGroup()
    for i in range(group.numDisplays()):group.getDisplayAt(i).setEnabled(False)
    displays={}
    for key in LAYERS:
        item=manager.createDisplay("rviz/PointCloud2",key,False)
        for prop,value in (("Topic",BASE+key),("Position Transformer","XYZ"),("Color Transformer","RGB8"),("Style","Points"),("Size (Pixels)",3),("Decay Time",0.),("Queue Size",1)):
            item.subProp(prop).setValue(value)
        displays[key]=item
    def change(*unused):
        for key,item in displays.items():item.setEnabled(key==combo.currentText() or (history_box.isChecked() and key=="past_context"))
    def set_meta(item):
        manager.setFixedFrame(item["frame_id"])
        camera=manager.getViewManager().getCurrent()
        for prop,key in (("Yaw","yaw"),("Pitch","pitch"),("Distance","distance")):camera.subProp(prop).setValue(item["view"][key])
        for prop,value in zip(("X","Y","Z"),item["view"]["center"]):camera.subProp("Focal Point").subProp(prop).setValue(value)
        notice.setText("%s | %s | 0.5 diagnostic; orange=dust, cyan=non-dust, red=FP, blue=FN, purple=no history. No free-space claim."%(item["uid"],item["frame_id"]))
    live=[None];last=[None]
    def update_meta():
        if live[0] and live[0]["uid"]!=last[0]:
            if args.capture and live[0]["uid"]!=meta["uid"]:return
            set_meta(live[0]);last[0]=live[0]["uid"]
    subscription=rospy.Subscriber(BASE+"source",String,lambda msg:live.__setitem__(0,json.loads(msg.data)),queue_size=1)
    timer=QtCore.QTimer();timer.timeout.connect(update_meta);timer.start(150)
    combo.currentTextChanged.connect(change);history_box.toggled.connect(change)
    change();set_meta(meta);window.resize(1024,720);window.show()
    if not args.capture:
        application.exec_();subscription.unregister();rospy.signal_shutdown("viewer closed");return
    out=args.capture;out.mkdir(exist_ok=False,parents=True)
    writer=ctypes.CDLL(str(Path(__file__).resolve().parent/"rviz_render.so")).save_review_target
    writer.argtypes=[ctypes.c_char_p];writer.restype=ctypes.c_int
    log=[];errors=[]
    def capture():
        try:
            name=args.layers[len(log)]
            if last[0]!=meta["uid"]:raise ValueError("source UID missing/mismatch")
            output=out/(name+".png")
            if int(writer(os.fsencode(output)))!=0:raise RuntimeError("OGRE capture failed")
            rgb=np.asarray(Image.open(output).convert("RGB"))
            varied=np.any(rgb!=rgb[0,0],axis=2)
            if name=="raw" and varied.mean()<.001:raise ValueError("no visible raw geometry")
            actual=manager.getViewManager().getCurrent()
            camera={prop:float(actual.subProp(prop).getValue()) for prop in ("Distance","Yaw","Pitch")}
            camera["center"]=[float(actual.subProp("Focal Point").subProp(k).getValue()) for k in ("X","Y","Z")]
            log.append(dict(layer=name,sha256=sha(output),camera=camera,varied_pixels=int(varied.sum()),
                            history_overlay=history_box.isChecked(),fixed_frame=meta["frame_id"],source=last[0]))
            QtCore.QTimer.singleShot(10,choose)
        except Exception as error: errors.append(repr(error));application.quit()
    def choose():
        if len(log)==len(args.layers):application.quit();return
        combo.setCurrentText(args.layers[len(log)]);history_box.setChecked(False);change()
        QtCore.QTimer.singleShot(950,capture)
    QtCore.QTimer.singleShot(2000,choose);QtCore.QTimer.singleShot(42000,application.quit)
    application.exec_()
    done=len(log)==len(args.layers) and not errors and all(r["camera"]==log[0]["camera"] for r in log)
    (out/"capture.json").write_text(json.dumps(dict(pass_checks=done,method="native OGRE offscreen render of active RViz camera; no desktop capture",rows=log,errors=errors),indent=2))
    if not done:raise RuntimeError("incomplete capture: "+str(errors))
    timer.stop();subscription.unregister();rospy.signal_shutdown("completed dedicated capture worker")
    sys.stdout.flush();sys.stderr.flush()
    os._exit(0)


if __name__=="__main__":
    guard()
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["play","view"]);parser.add_argument("--book",required=True,type=Path)
    parser.add_argument("--case",type=int,default=1);parser.add_argument("--rate",type=float,default=1)
    parser.add_argument("--log",type=Path,default=Path("/tmp/mining-review.log"))
    parser.add_argument("--capture",type=Path);parser.add_argument("--layers",nargs="+",choices=LAYERS,default=["raw","reference","single","temporal","temporal_error","unavailable"])
    opts=parser.parse_args()
    (play if opts.action=="play" else view)(opts)
