"""One registered public training frame, private localhost master, native RViz display."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import xmlrpc.client
import numpy as np

LAYERS=("raw","valid","reference","ignored","index")
BASE="/datahub_mining/"
DTYPE=np.dtype([("x","<f4"),("y","<f4"),("z","<f4"),("intensity","<f4"),("rgb","<u4"),
                ("source_point_index","<u4"),("semantic_raw","u1"),("task_label","u1"),("geometry_valid","u1"),("supervision","u1")])


def arrays(folder):
    meta=json.loads((folder/"review.json").read_text())
    expected=json.loads((folder/"input.json").read_text())
    if meta["split"]!="train" or meta["source_ref"]!="interior1/Area_1/amtc_068" or meta["frame_uid"]!=expected["row"]["frame_uid"]:
        raise ValueError("expected registered public training case")
    with np.load(folder/"sample.npz",allow_pickle=False) as file:
        src=dict(file)
    for key,des in expected["arrays"].items():
        a=np.ascontiguousarray(src[key])
        if a.dtype.str!=des["dtype"] or list(a.shape)!=des["shape"] or hashlib.sha256(a.tobytes()).hexdigest()!=des["sha256"]:
            raise ValueError("input digest mismatch: "+key)
    if src["source_point_index"].max(initial=0)>np.iinfo(np.uint32).max:raise ValueError("index exceeds wire uint32")
    raw=np.zeros(len(src["valid"]),dtype=DTYPE)
    for name,val in zip(("x","y","z"),src["xyz"].T):raw[name]=val
    for name,key in (("intensity","intensity"),("source_point_index","source_point_index"),("semantic_raw","semantic_raw"),
                     ("task_label","task_label"),("geometry_valid","valid"),("supervision","supervision_mask")):
        raw[name]=src[key]
    good=np.asarray(src["valid"],bool);visible=good & np.isfinite(src["intensity"])
    intensity=np.arcsinh(np.nan_to_num(src["intensity"]));lo,hi=np.percentile(intensity[visible],[2,98])
    raw["rgb"]=(40+215*np.clip((intensity-lo)/max(hi-lo,1e-8),0,1)).astype(np.uint32)*0x010101
    valid=raw[good].copy()
    reference=raw[good & src["supervision_mask"]].copy()
    reference["rgb"]=np.where(reference["task_label"]==2,0xf0882d,0x1bc4a7)
    ignored=raw[good & ~src["supervision_mask"]].copy();ignored["rgb"]=0xba78ed
    indices=valid.copy()
    indices["rgb"]=(0x303030 | ((indices["source_point_index"].astype(np.uint64)*2654435761 >> 9) & 0xcfcfcf)).astype(np.uint32)
    return meta,dict(raw=raw,valid=valid,reference=reference,ignored=ignored,index=indices)


def fields():
    from sensor_msgs.msg import PointField
    types={"f":PointField.FLOAT32,"u":PointField.UINT32}
    return [PointField(name=k,offset=DTYPE.fields[k][1],datatype=PointField.UINT8 if DTYPE[k].itemsize==1 else types[DTYPE[k].kind],count=1) for k in DTYPE.names]


def message(meta,arr,layer):
    import rospy
    from sensor_msgs.msg import PointCloud2
    msg=PointCloud2()
    stamp=meta.get("stamp_ns")
    ns=0 if stamp is None else int(stamp)
    msg.header.stamp=rospy.Time(ns//10**9,ns%10**9);msg.header.frame_id=meta["frame_id"]
    msg.fields=fields();msg.height=1;msg.width=len(arr);msg.is_bigendian=False;msg.point_step=DTYPE.itemsize
    msg.is_dense=bool(np.isfinite(arr["x"]).all() and np.isfinite(arr["y"]).all() and np.isfinite(arr["z"]).all())
    msg.row_step=len(arr)*msg.point_step;msg.data=arr.tobytes();return msg


def viewer(args):
    from PyQt5 import QtCore,QtWidgets
    from rviz import bindings as rviz
    from PIL import Image
    meta,cloud=arrays(args.case_dir)
    application=QtWidgets.QApplication([])
    window=QtWidgets.QWidget();window.setWindowTitle("Single-LiDAR mining sample: source labels")
    layout=QtWidgets.QVBoxLayout(window)
    layout.addWidget(QtWidgets.QLabel(f"UCHILE | {meta['source_ref']} | train | processed coordinates | no cloud timestamp"))
    combo=QtWidgets.QComboBox();combo.addItems(LAYERS);layout.addWidget(combo)
    layout.addWidget(QtWidgets.QLabel("Cyan: publisher non-dust; orange: publisher dust. Index colors are illustrative; exact uint32 is in the message."))
    visual=rviz.VisualizationFrame();visual.setSplashPath("");visual.initialize(str(Path(__file__).with_name("mining_view.rviz")))
    visual.setMenuBar(None);visual.setStatusBar(None);layout.addWidget(visual)
    manager=visual.getManager();manager.setFixedFrame(meta["frame_id"])
    group=manager.getRootDisplayGroup()
    for i in range(group.numDisplays()):group.getDisplayAt(i).setEnabled(False)
    displays={}
    for key in LAYERS:
        display=manager.createDisplay("rviz/PointCloud2",key,False)
        for prop,val in (("Topic",BASE+key),("Position Transformer","XYZ"),("Color Transformer","RGB8"),("Style","Points"),("Size (Pixels)",3),("Queue Size",1)):
            display.subProp(prop).setValue(val)
        displays[key]=display
    cam=manager.getViewManager().getCurrent()
    for key,val in (("Distance",7.),("Yaw",.75),("Pitch",.46)):cam.subProp(key).setValue(val)
    for key,val in zip("XYZ",(.45,-.05,.30)):cam.subProp("Focal Point").subProp(key).setValue(val)
    def choose(*unused):
        for key,d in displays.items():d.setEnabled(combo.currentText()==key)
    combo.currentTextChanged.connect(choose);choose();window.resize(1080,740);window.show()
    if not args.capture:
        application.exec_();return
    if not args.renderer:raise ValueError("native renderer path required for capture")
    writer=ctypes.CDLL(str(args.renderer.resolve())).save_review_target
    writer.argtypes=[ctypes.c_char_p];writer.restype=ctypes.c_int
    args.capture.mkdir(exist_ok=False);observed=[];errors=[]
    def capture():
        try:
            name=combo.currentText();dest=args.capture/(name+".png")
            if writer(os.fsencode(dest))!=0:raise ValueError("RViz native render failed")
            pixels=np.asarray(Image.open(dest).convert("RGB"))
            varied=np.any(pixels!=pixels[0,0],axis=2)
            if len(cloud[name]) and int(varied.sum())<300:raise ValueError("nonempty layer has no visible geometry: "+name)
            camera={k:float(cam.subProp(k).getValue()) for k in ("Distance","Yaw","Pitch")}
            camera["center"]=[float(cam.subProp("Focal Point").subProp(k).getValue()) for k in "XYZ"]
            observed.append(dict(layer=name,count=len(cloud[name]),colored_pixels=int(varied.sum()),
                                 sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),camera=camera))
            if len(observed)==len(LAYERS):application.quit();return
            combo.setCurrentIndex(len(observed));QtCore.QTimer.singleShot(1000,capture)
        except Exception as exc:errors.append(repr(exc));application.quit()
    QtCore.QTimer.singleShot(3300,capture);QtCore.QTimer.singleShot(25000,application.quit)
    application.exec_()
    ok=len(observed)==len(LAYERS) and not errors and all(r["camera"]==observed[0]["camera"] for r in observed)
    (args.capture/"capture.json").write_text(json.dumps(dict(pass_checks=ok,rows=observed,errors=errors,source=meta,method="native RViz OGRE target"),indent=2))
    if not ok:raise RuntimeError("RViz capture failed "+str(errors))
    sys.stdout.flush();sys.stderr.flush();os._exit(0)


def session(args):
    import rospy
    from sensor_msgs.msg import PointCloud2
    meta,cloud=arrays(args.case_dir)
    port=args.port;uri=f"http://127.0.0.1:{port}"
    if port<11450 or port>11499:raise ValueError("use reserved review range 11450–11499")
    if os.environ.get("ROS_MASTER_URI")!=uri or os.environ.get("ROS_IP")!="127.0.0.1" or os.environ.get("ROS_HOSTNAME"):
        raise RuntimeError("use the isolated loopback environment in the instructions")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",port))
    args.out.mkdir(exist_ok=False,parents=True)
    with (args.out/"roscore.log").open("w") as log:
        core=subprocess.Popen(["roscore","-p",str(port)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        observed=[];complete=False
        try:
            deadline=time.monotonic()+16
            while time.monotonic()<deadline and core.poll() is None:
                try:
                    if xmlrpc.client.ServerProxy(uri).getUri("/mining_local_check")[0]==1:break
                except OSError:pass
                time.sleep(.15)
            else:raise RuntimeError("own master did not start")
            rospy.init_node("mining_train_preview",anonymous=True,disable_signals=True,log_level=rospy.WARN)
            pubs=[rospy.Publisher(BASE+k,PointCloud2,queue_size=1,latch=True) for k in LAYERS]
            for key,pub in zip(LAYERS,pubs):
                expected=message(meta,cloud[key],key);pub.publish(expected)
                msg=rospy.wait_for_message(BASE+key,PointCloud2,timeout=5)
                if msg.data!=expected.data or msg.fields!=expected.fields or msg.header.frame_id!=meta["frame_id"] or msg.header.stamp!=expected.header.stamp or msg.width!=len(cloud[key]) or msg.row_step!=len(msg.data):
                    raise ValueError("PointCloud2 wire mismatch: "+key)
                got=np.frombuffer(msg.data,DTYPE)
                np.testing.assert_array_equal(got["source_point_index"],cloud[key]["source_point_index"])
                observed.append(dict(layer=key,width=msg.width,bytes=len(msg.data),source_indices_match=True,payload_sha256=hashlib.sha256(msg.data).hexdigest()))
            command=[sys.executable,"-B",__file__,"view","--port",str(port),"--case-dir",str(args.case_dir.resolve())]
            if args.renderer:command+=["--renderer",str(args.renderer.resolve()),"--capture",str((args.out/"images").resolve())]
            with (args.out/"viewer.log").open("w") as log:
                subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=65 if args.renderer else None)
            complete=True
        finally:
            rospy.signal_shutdown("own preview complete")
            if core.poll() is None:os.killpg(core.pid,signal.SIGINT)
            core.wait(timeout=20)
            (args.out/"wire.json").write_text(json.dumps(dict(complete=complete,source=meta,observed=observed,
                         master_port=port,own_master_exit=core.returncode,clock="zero means source header unavailable"),indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["view","session"])
    parser.add_argument("--case-dir",required=True,type=Path);parser.add_argument("--out",type=Path)
    parser.add_argument("--port",type=int,default=11483);parser.add_argument("--renderer",type=Path)
    parser.add_argument("--capture",type=Path)
    args=parser.parse_args()
    if (not 11450<=args.port<=11499 or os.environ.get("ROS_MASTER_URI")!=f"http://127.0.0.1:{args.port}" or
        os.environ.get("ROS_IP")!="127.0.0.1" or os.environ.get("ROS_HOSTNAME")):
        raise RuntimeError("dedicated localhost review environment required")
    (session if args.mode=="session" else viewer)(args)
