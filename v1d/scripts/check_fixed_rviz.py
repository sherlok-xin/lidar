#!/usr/bin/env python3
"""Bounded D-only master/player around native single-window fixed-camera evidence."""
import argparse,json,os,signal,socket,subprocess,sys,time,xmlrpc.client
from pathlib import Path
D=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--seq',type=int,required=True);p.add_argument('--topics',nargs='+',required=True);a=p.parse_args();out=Path(a.output).resolve()
    try:out.relative_to(D)
    except ValueError:raise ValueError('D evidence only')
    s=socket.socket();busy=s.connect_ex(('127.0.0.1',11331))==0;s.close()
    if busy:raise RuntimeError('Do not attach to existing D master')
    out.mkdir(parents=True,exist_ok=False);env=dict(os.environ,ROS_MASTER_URI='http://127.0.0.1:11331',ROS_IP='127.0.0.1',PYTHONDONTWRITEBYTECODE='1',
        ROS_HOME=str(D/'.ros'),ROS_LOG_DIR=str(out/'ros_logs'),XDG_CONFIG_HOME=str(D/'.config'),XDG_CACHE_HOME=str(D/'.cache'),XDG_RUNTIME_DIR=str(D/'.runtime'),
        DISABLE_ROS1_EOL_WARNINGS='1',LIBGL_ALWAYS_SOFTWARE='1');env.pop('ROS_HOSTNAME',None)
    for k in ['ROS_HOME','ROS_LOG_DIR','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_RUNTIME_DIR']:Path(env[k]).mkdir(parents=True,exist_ok=True)
    Path(env['XDG_RUNTIME_DIR']).chmod(0o700);children=[];handles=[];result={'seq':a.seq,'topics':a.topics,'commands':[]}
    def start(cmd,name):
        h=(out/(name+'.log')).open('w');handles.append(h);q=subprocess.Popen(cmd,env=env,stdout=h,stderr=subprocess.STDOUT,start_new_session=True);children.append(q);result['commands'].append(dict(name=name,pid=q.pid,argv=cmd));return q
    try:
        start(['roscore','-p','11331'],'master');rpc=xmlrpc.client.ServerProxy(env['ROS_MASTER_URI'])
        for _ in range(100):
            try:
                if rpc.getPid('/opdf_fixed_check')[0]==1:break
            except OSError:pass
            time.sleep(.1)
        else:raise RuntimeError('Own master did not start')
        rpc.setParam('/opdf_fixed_check','/use_sim_time',True)
        player=start([sys.executable,'-B',str(D/'scripts/frame_review_ros1.py'),'--index',str(D/'outputs/d2_candidate/fusion/debug_frame_index.json'),
            '--seq',str(a.seq),'--clock','--once','--hold-seconds','35','--refresh-hz','2','--log',str(out/'player_events.jsonl')],'player')
        gui=start([sys.executable,'-B',str(D/'scripts/rviz_fixed_views.py'),'--output',str(out/'views'),'--topics',*a.topics],'native_rviz')
        code=gui.wait(timeout=48)
        if code:raise RuntimeError('Native fixed-camera GUI failed, see original log')
        result.update(pass_check=True,camera_verified_in= str(out/'views/camera_and_layers.json'))
    except Exception as exc:result.update(pass_check=False,error=str(exc));raise
    finally:
        for q in reversed(children):
            if q.poll()is None:
                try:os.killpg(q.pid,signal.SIGINT);q.wait(timeout=4)
                except (ProcessLookupError,subprocess.TimeoutExpired):
                    try:os.killpg(q.pid,signal.SIGTERM);q.wait(timeout=3)
                    except (ProcessLookupError,subprocess.TimeoutExpired):pass
        for h in handles:h.close()
        result['child_exit_codes']=[dict(pid=q.pid,code=q.poll())for q in children]
        (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
