#!/usr/bin/env python3
"""Real native RViz VisualizationFrame, one window and measured identical camera."""
import argparse,json,os,sys
from pathlib import Path
sys.dont_write_bytecode=True
D=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--topics',nargs='+',required=True);a=p.parse_args();out=Path(a.output).resolve()
    try:out.relative_to(D)
    except ValueError:raise ValueError('D evidence only')
    if os.environ.get('ROS_MASTER_URI')!='http://127.0.0.1:11331':raise ValueError('Isolated D master only')
    out.mkdir(parents=True,exist_ok=False)
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer
    from rviz import bindings as rviz
    app=QApplication([]);frame=rviz.VisualizationFrame();frame.setSplashPath('');frame.initialize()
    config=rviz.Config();reader=rviz.YamlConfigReader();reader.readFile(config,str(D/'configs/opdf_debug_ros1.rviz'));frame.load(config)
    frame.resize(1400,950);frame.show();manager=frame.getManager();root=manager.getRootDisplayGroup();layers={}
    for i in range(root.numDisplays()):
        display=root.getDisplayAt(i);topic=display.subProp('Topic').getValue()
        if topic:layers[str(topic)]=display
    if any(t not in layers for t in a.topics):raise ValueError('Requested topic is not in RViz config')
    records=[];position=[0];failed=[]
    def set_camera():
        view=manager.getViewManager().getCurrent()
        for name,value in [('Distance',35.),('Yaw',.8),('Pitch',.35)]:view.subProp(name).setValue(value)
        focal=view.subProp('Focal Point')
        for name,value in [('X',0.),('Y',5.),('Z',-.5)]:focal.subProp(name).setValue(value)
        return view
    def select_layer():
        try:
            if position[0]>=len(a.topics):app.quit();return
            topic=a.topics[position[0]]
            for t,display in layers.items():display.setEnabled(t==topic)
            set_camera();QTimer.singleShot(1800,capture)
        except Exception as exc:failed.append(str(exc));app.quit()
    def capture():
        try:
            view=set_camera();app.processEvents()
            camera={n:float(view.subProp(n).getValue()) for n in ['Distance','Yaw','Pitch']}
            focal=view.subProp('Focal Point');camera['Focal Point']={n:float(focal.subProp(n).getValue())for n in ['X','Y','Z']}
            topic=a.topics[position[0]];name=topic.rsplit('/',1)[1];app.processEvents()
            pix=app.primaryScreen().grabWindow(int(frame.winId()))
            if pix.isNull()or not pix.save(str(out/(name+'.png'))):raise RuntimeError('Actual native window capture failed')
            records.append(dict(topic=topic,camera=camera,enabled_topics=[t for t,d in layers.items()if d.isEnabled()],
                fixed_frame=str(manager.getFixedFrame()),scope='actual native RViz, not Matplotlib or synthetic'))
            position[0]+=1;QTimer.singleShot(200,select_layer)
        except Exception as exc:failed.append(str(exc));app.quit()
    QTimer.singleShot(4000,select_layer);QTimer.singleShot(45000,app.quit);app.exec_()
    result=dict(pass_check=not failed and len(records)==len(a.topics),camera_equal=bool(records)and all(r['camera']==records[0]['camera']for r in records),
        records=records,errors=failed,source='existing Noetic librviz_sip native VisualizationFrame; one window',
        source_config=str(D/'configs/opdf_debug_ros1.rviz'))
    (out/'camera_and_layers.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    if not result['pass_check']or not result['camera_equal']:raise SystemExit(2)

if __name__=='__main__':main()
