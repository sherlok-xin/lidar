#!/usr/bin/env python3
"""Bounded actual RViz layout check; existing full pub/sub check is separate."""
import argparse,copy,json,os,signal,socket,subprocess,sys,time,xmlrpc.client
from pathlib import Path
import yaml
C=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    p.add_argument('--index',default=str(C/'outputs/v1b_continuous30/debug_frame_index.json'))
    p.add_argument('--only-suspect',action='store_true');a=p.parse_args();E=Path(a.output).resolve()
    try:E.relative_to(C)
    except ValueError:raise ValueError('Evidence must remain V1-C')
    if os.environ.get('ROS_MASTER_URI')!='http://127.0.0.1:11321' or os.environ.get('ROS_IP')!='127.0.0.1':raise ValueError('Isolated loopback required')
    s=socket.socket();busy=s.connect_ex(('127.0.0.1',11321))==0;s.close()
    if busy:raise RuntimeError('Port in use; do not attach to an existing master')
    E.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,DISABLE_ROS1_EOL_WARNINGS='1',LIBGL_ALWAYS_SOFTWARE='1',PYTHONDONTWRITEBYTECODE='1',
             ROS_HOME=str(C/'.ros'),ROS_LOG_DIR=str(E/'ros_logs'),XDG_CACHE_HOME=str(C/'.cache'),
             XDG_CONFIG_HOME=str(C/'.config'),XDG_RUNTIME_DIR=str(C/'.runtime'))
    env.pop('ROS_HOSTNAME',None)
    for k in ['ROS_HOME','ROS_LOG_DIR','XDG_CACHE_HOME','XDG_CONFIG_HOME','XDG_RUNTIME_DIR']:Path(env[k]).mkdir(parents=True,exist_ok=True)
    Path(env['XDG_RUNTIME_DIR']).chmod(0o700)
    procs=[];handles=[];summary={'scope':'actual own X11 RViz, source seq245847, fixed same camera; GUI-only after full330 network check','commands':[]}
    def start(cmd,name):
        h=(E/(name+'.log')).open('w');handles.append(h)
        q=subprocess.Popen(cmd,env=env,stdout=h,stderr=subprocess.STDOUT,start_new_session=True);procs.append(q)
        summary['commands'].append(dict(name=name,pid=q.pid,argv=cmd));return q
    try:
        start(['roscore','-p','11321'],'roscore');rpc=xmlrpc.client.ServerProxy(env['ROS_MASTER_URI'])
        for _ in range(100):
            try:
                if rpc.getPid('/opdf_gui_check')[0]==1:break
            except OSError:pass
            time.sleep(.1)
        else:raise RuntimeError('Own debug master did not start')
        rpc.setParam('/opdf_gui_check','/use_sim_time',True)
        base=yaml.safe_load((C/'configs/opdf_debug_ros1.rviz').read_text());gui_configs=[]
        displays=[('suspect','/opdf_v1/aerosol_suspect')] if a.only_suspect else [('raw','/opdf_v1/raw'),('classified','/opdf_v1/class_rgb')]
        for name,topic in displays:
            cfg=copy.deepcopy(base)
            for d in cfg['Visualization Manager']['Displays']:
                if d.get('Class')=='rviz/PointCloud2':d['Enabled']=d.get('Topic')==topic
            f=E/('rviz_'+name+'.rviz');f.write_text(yaml.safe_dump(cfg,sort_keys=False))
            gui_configs.append((name,f))
        index=a.index
        player=start([sys.executable,'-B',str(C/'scripts/frame_review_ros1.py'),'--index',index,'--seq','245847',
                      '--clock','--once','--hold-seconds','18' if a.only_suspect else '35','--refresh-hz','2','--log',str(E/'player_events.jsonl')],'player')
        # One RViz at a time: QScreen capture can include an overlapping foreign
        # window even when its requested native ID is correct. Avoid occlusion.
        for name,f in gui_configs:
            q=start(['rviz','-d',str(f)],'rviz_'+name);time.sleep(6)
            if q.poll() is not None:raise RuntimeError('RViz exited before capture')
            cmd=[sys.executable,'-B',str(C/'scripts/capture_rviz_window.py'),'--pid',str(q.pid),'--output',str(E/('rviz_'+name+'.png'))]
            r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=12)
            (E/('capture_'+name+'.log')).write_text(r.stdout+'\n'+r.stderr)
            if r.returncode:raise RuntimeError('Actual capture failed '+r.stderr)
            try:os.killpg(q.pid,signal.SIGINT);q.wait(timeout=3)
            except subprocess.TimeoutExpired:os.killpg(q.pid,signal.SIGTERM);q.wait(timeout=3)
        player.wait(timeout=40)
        if player.returncode:raise RuntimeError('Player failed')
        summary.update(pass_process_check=True,screenshots_created=True,source_seq=245847,
                       header_and_record_preserved=True,semantic_GT=False,
                       visual_quality_requires_inspection=True,software_renderer=True)
    except Exception as e:summary.update(pass_process_check=False,error=str(e));raise
    finally:
        for q in reversed(procs):
            if q.poll() is None:
                try:os.killpg(q.pid,signal.SIGINT);q.wait(timeout=4)
                except (ProcessLookupError,subprocess.TimeoutExpired):
                    try:os.killpg(q.pid,signal.SIGTERM);q.wait(timeout=3)
                    except (ProcessLookupError,subprocess.TimeoutExpired):pass
        for h in handles:h.close()
        summary['owned_children_exit_codes']=[dict(pid=q.pid,code=q.poll()) for q in procs]
        (E/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))

if __name__=='__main__':main()
