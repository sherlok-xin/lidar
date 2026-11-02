#!/usr/bin/env python3
"""Bounded actual isolated ROS1 pub/sub and optional real RViz check. Not vehicle ROS."""
import argparse
from collections import defaultdict
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import xmlrpc.client

C=Path(__file__).resolve().parents[1]

def digest(msg):
    s=io.BytesIO();msg.serialize(s);return hashlib.sha256(s.getvalue()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--index',required=True);p.add_argument('--gui',action='store_true');p.add_argument('--output',default=str(C/'evidence/ros1_actual'));a=p.parse_args()
    if os.environ.get('ROS_MASTER_URI')!='http://127.0.0.1:11331' or os.environ.get('ROS_IP')!='127.0.0.1':raise ValueError('Explicit isolated loopback master required')
    s=socket.socket();busy=s.connect_ex(('127.0.0.1',11331))==0;s.close()
    if busy:raise RuntimeError('Debug port already occupied; will not connect or stop an existing master')
    E=Path(a.output).resolve()
    try:E.relative_to(C)
    except ValueError:raise ValueError('Evidence output must remain in V1-C')
    E.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',DISABLE_ROS1_EOL_WARNINGS='1',LIBGL_ALWAYS_SOFTWARE='1',ROS_HOME=str(C/'.ros'),ROS_LOG_DIR=str(E/'ros_logs'),
             XDG_CACHE_HOME=str(C/'.cache'),XDG_CONFIG_HOME=str(C/'.config'),XDG_RUNTIME_DIR=str(C/'.runtime'))
    env.pop('ROS_HOSTNAME',None)
    for key in ['ROS_HOME','ROS_LOG_DIR','XDG_CACHE_HOME','XDG_CONFIG_HOME','XDG_RUNTIME_DIR']:
        Path(env[key]).mkdir(parents=True,exist_ok=True)
    Path(env['XDG_RUNTIME_DIR']).chmod(0o700)
    os.environ.update({k:env[k] for k in ('ROS_HOME','ROS_LOG_DIR','XDG_CACHE_HOME','XDG_CONFIG_HOME','XDG_RUNTIME_DIR')})
    children=[];logs=[];summary=dict(scope='real isolated ROS1; all child processes owned and bounded',gui_requested=a.gui,commands=[])
    def start(cmd,name):
        f=(E/(name+'.log')).open('w');logs.append(f)
        proc=subprocess.Popen(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True);children.append(proc)
        summary['commands'].append(dict(name=name,argv=cmd,pid=proc.pid));return proc
    def wait(proc,timeout):
        code=proc.wait(timeout=timeout)
        if code:raise RuntimeError('Child failed '+str(proc.args)+' code '+str(code))
    try:
        master=start(['roscore','-p','11331'],'roscore')
        rpc=xmlrpc.client.ServerProxy(env['ROS_MASTER_URI'])
        for _ in range(100):
            try:
                if rpc.getPid('/opdf_v1c_actual_check')[0]==1:break
            except OSError:pass
            time.sleep(.1)
        else:raise RuntimeError('Own isolated master did not start')
        import rospy,rosbag
        from sensor_msgs.msg import PointCloud2
        from rosgraph_msgs.msg import Clock
        rospy.set_param('/use_sim_time',True) # before RViz/subscriber initialization
        index=json.loads(Path(a.index).read_text());allowed=set(index['topics']);expected={};bag_read_start=time.monotonic()
        with rosbag.Bag(index['bag_path'],'r') as bag:
            for topic,msg,stamp in bag.read_messages():
                if topic not in allowed:raise RuntimeError('Bag contains undeclared topic')
                expected[(msg.header.seq,topic)]=(digest(msg),msg.height*msg.width)
        summary['expected_read_hash_seconds']=time.monotonic()-bag_read_start
        rospy.init_node('opdf_v1c_actual_check',anonymous=True,disable_signals=True)
        received=defaultdict(int);complete=defaultdict(set);clears=defaultdict(int);errors=[];clocks=[]
        def receive(topic,msg):
            key=(msg.header.seq,topic)
            if key not in expected:errors.append('unindexed '+repr(key));return
            want,n=expected[key]
            if n and msg.height*msg.width==0:clears[topic]+=1;return
            if digest(msg)!=want:errors.append('full serialization mismatch '+repr(key));return
            received[key]+=1;complete[msg.header.seq].add(topic)
        subs=[rospy.Subscriber(t,PointCloud2,lambda m,t=t:receive(t,m),queue_size=10,buff_size=16*1024*1024) for t in sorted(allowed)]
        clocksub=rospy.Subscriber('/clock',Clock,lambda m:clocks.append(m.clock.to_nsec()),queue_size=100)
        player=C/'scripts/frame_review_ros1.py'
        first=index['frames'][0]['seq'];middle=index['frames'][len(index['frames'])//2]['seq']
        cmds='seq:{},play:{},pause,seq:{},next,prev,seq:{},pause,quit'.format(first,max(2,len(index['frames'])/3+1),middle,first)
        pr=start([sys.executable,'-B',str(player),'--index',a.index,'--seq',str(middle),'--clock','--rate','3','--refresh-hz','1','--command-delay','.8','--commands',cmds,'--log',str(E/'player_events.jsonl')],'player')
        wait(pr,45);time.sleep(.5)
        missing=[dict(seq=k[0],topic=k[1]) for k in expected if not received[k]]
        backward=sum(b<a for a,b in zip(clocks,clocks[1:]))
        source_clocks={f['record_stamp_ns'] for f in index['frames']}
        unexpected_clocks=sorted(set(clocks)-source_clocks)
        missing_clocks=sorted(source_clocks-set(clocks))
        summary.update(expected_frame_topics=len(expected),received_distinct_frame_topics=sum(bool(received[k]) for k in expected),
                       complete_source_frames=sum(complete[f['seq']]==allowed for f in index['frames']),
                       received_messages=sum(received.values()),mismatches=errors,missing=missing,
                       backward_clock_jumps=backward,empty_refresh_clouds=dict(clears),simulated_clock='exact source record ns',
                       received_clock_ns=clocks,not_in_source_record_ns=unexpected_clocks,
                       source_records_not_received_as_clock_ns=missing_clocks,
                       exact_clock_values_pass=bool(clocks) and not unexpected_clocks and not missing_clocks,
                       seq_header_fields_xyz_rgb_slot_check='full ROS1 serialization hash per seq/topic against separately read exported bag',
                       gui_verified=False)
        if errors or missing or not backward or unexpected_clocks or missing_clocks:raise RuntimeError('Actual pub/sub or clock check failed')
        if a.gui:
            import yaml
            cfg=yaml.safe_load((C/'configs/opdf_debug_ros1.rviz').read_text())
            gui=[]
            for name,topic in [('raw','/opdf_v1/raw'),('classified','/opdf_v1/class_rgb')]:
                import copy
                c=copy.deepcopy(cfg)
                for layer in c['Visualization Manager']['Displays']:
                    if layer.get('Class')=='rviz/PointCloud2':layer['Enabled']=layer.get('Topic')==topic
                path=E/('rviz_'+name+'.rviz');path.write_text(yaml.safe_dump(c,sort_keys=False))
                proc=start(['rviz','-d',str(path)],'rviz_'+name);gui.append((name,proc))
            view=start([sys.executable,'-B',str(player),'--index',a.index,'--seq',str(middle),'--clock','--once','--hold-seconds','18','--refresh-hz','2','--log',str(E/'gui_player_events.jsonl')],'gui_player')
            time.sleep(9)
            captures=[]
            for name,proc in gui:
                if proc.poll() is not None:raise RuntimeError('RViz GUI process exited; see log')
                cmd=[sys.executable,'-B',str(C/'scripts/capture_rviz_window.py'),'--pid',str(proc.pid),'--output',str(E/('rviz_'+name+'.png'))]
                got=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=10)
                (E/('capture_'+name+'.log')).write_text(got.stdout+'\n'+got.stderr)
                if got.returncode:raise RuntimeError('Own RViz capture failed: '+got.stderr)
                captures.append(str(E/('rviz_'+name+'.png')))
            summary.update(gui_verified=True,gui_scope='two actual own RViz windows at same source frame/camera, captured through X11; no human semantic GT',screenshots=captures)
            wait(view,25)
        summary['pass_check']=True
    except Exception as exc:
        summary.update(pass_check=False,error=type(exc).__name__+': '+str(exc));raise
    finally:
        # Terminate only processes this check created; existing 11311 master is untouched.
        for proc in reversed(children):
            if proc.poll() is None:
                try:os.killpg(proc.pid,signal.SIGINT);proc.wait(timeout=5)
                except (ProcessLookupError,subprocess.TimeoutExpired):
                    try:os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=3)
                    except (ProcessLookupError,subprocess.TimeoutExpired):pass
        for f in logs:f.close()
        summary['owned_children_exit_codes']=[dict(pid=p.pid,code=p.poll()) for p in children]
        (E/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
