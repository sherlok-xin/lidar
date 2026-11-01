#!/usr/bin/env python3
"""ROS1 whole-source-frame debug player. No numpy, algorithm or bag export.

Commands (Enter after each): n/p, seq N, play/pause, rate FPS, status, q.
Only the isolated loopback master :11321 is accepted. A logical frame batch
is validated before publishing; ROS1 topics are NOT a network transaction.
"""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import select
import sys
import time
from urllib.parse import urlparse

sys.dont_write_bytecode = True
V1C = Path(__file__).resolve().parents[1]
PRIMARY = tuple('/opdf_v1/'+s for s in ('raw','nonground','class_rgb','entity_only',
                'aerosol_strong','unknown','ground','retained'))
ALLOWED = set(PRIMARY) | {'/opdf_v1/optical_rgb','/opdf_v1/scan_rgb','/opdf_v1/spatial_rgb',
                        '/opdf_v1/aerosol_suspect','/opdf_v1/entity_optical_conflict'}
MASTER = 'http://127.0.0.1:11321'
_SOURCE_HEADER_CLASS = None


def source_header_message(message):
    """Skip rospy's seq rewrite without changing ROS type, MD5 or wire fields.

    rospy.msg.serialize_message checks the concrete Python class _has_header;
    the generated PointCloud2 serializer still writes the original Header.
    Publisher remains advertised as sensor_msgs/PointCloud2. No global class or
    rospy function is patched and AnyMsg is never used.
    """
    global _SOURCE_HEADER_CLASS
    from sensor_msgs.msg import PointCloud2
    if getattr(message,'_type',None)!=PointCloud2._type or getattr(message,'_md5sum',None)!=PointCloud2._md5sum:
        raise ValueError('Only a genuine PointCloud2 wire schema can preserve source headers')
    if _SOURCE_HEADER_CLASS is None:
        class SourceHeaderPointCloud2(PointCloud2):
            _has_header = False
        _SOURCE_HEADER_CLASS=SourceHeaderPointCloud2
    out=_SOURCE_HEADER_CLASS()
    for name in PointCloud2.__slots__:
        setattr(out,name,copy.deepcopy(message.header) if name=='header' else getattr(message,name))
    return out


def under(path,root):
    # ROS Noetic containers may use Python 3.8 (no Path.is_relative_to).
    return path==root or root in path.parents


def guard_environment():
    os.environ.setdefault('ROS_MASTER_URI', MASTER)
    os.environ.setdefault('ROS_IP', '127.0.0.1')
    os.environ.setdefault('ROS_LOG_DIR', str(V1C/'evidence/ros_logs'))
    uri = urlparse(os.environ['ROS_MASTER_URI'])
    if uri.scheme != 'http' or uri.hostname not in ('127.0.0.1','localhost') or uri.port != 11321:
        raise ValueError('Refusing production/other master; explicitly use loopback ROS_MASTER_URI :11321')
    if os.environ.get('ROS_IP') != '127.0.0.1' or os.environ.get('ROS_HOSTNAME') not in (None,'','localhost','127.0.0.1'):
        raise ValueError('Debug ROS_IP/ROS_HOSTNAME must remain loopback')
    logs = Path(os.environ['ROS_LOG_DIR']).resolve()
    if not under(logs,V1C):
        raise ValueError('ROS_LOG_DIR must be under opdf_v1/v1c')
    logs.mkdir(parents=True,exist_ok=True)


def load_index(path):
    p=Path(path).resolve();index=json.loads(p.read_text())
    frames=index.get('frames',[])
    if not frames or len(frames)>300:
        raise ValueError('Expected 1..300 explicitly indexed source frames')
    seqs=[]
    for row in frames:
        for key in ('seq','header_stamp_ns','record_stamp_ns'):
            if isinstance(row.get(key),bool) or not isinstance(row.get(key),int):
                raise ValueError(f'Exact integer {key} is required')
        topics=row.get('topics',index.get('topics',[]))
        if not set(PRIMARY).issubset(topics) or not set(topics).issubset(ALLOWED):
            raise ValueError('Frame must contain all 8 primary topics and no undeclared topic')
        seqs.append(row['seq'])
    if len(seqs)!=len(set(seqs)):
        raise ValueError('Duplicate source sequences in frame index')
    bag=Path(index['bag_path'])
    if not bag.is_absolute():bag=p.parent/bag
    return dict(index,bag_path=str(bag.resolve()),frames=frames)


class FrameController:
    """Pure navigation state. Source stamps are never synthesized."""
    def __init__(self,frames,start_seq=None,rate=10.):
        self.frames=frames;self.position=0;self.playing=False;self.rate=float(rate)
        self.seek_by_seq={f['seq']:i for i,f in enumerate(frames)}
        self._rate(self.rate)
        if start_seq is not None:self.position=self.seek_by_seq[start_seq]
    def _rate(self,value):
        if not .1<=value<=30:raise ValueError('Frame rate must be .1..30 FPS')
        self.rate=value
    def command(self,text):
        parts=text.strip().lower().split()
        if not parts:return 'noop'
        cmd=parts[0];old=self.position
        if cmd in ('show',):pass
        elif cmd in ('n','next'):self.position=min(len(self.frames)-1,self.position+1)
        elif cmd in ('p','prev','previous'):self.position=max(0,self.position-1)
        elif cmd in ('seq','g'):
            if len(parts)!=2 or int(parts[1]) not in self.seek_by_seq:raise ValueError('Requested seq is not in this indexed source window')
            self.position=self.seek_by_seq[int(parts[1])]
        elif cmd in ('play','a'):self.playing=True;return 'play'
        elif cmd in ('pause','stop'):self.playing=False;return 'pause'
        elif cmd in ('rate','r'):
            if len(parts)!=2:raise ValueError('Use rate FPS')
            self._rate(float(parts[1]));return 'rate'
        elif cmd in ('q','quit'):return 'quit'
        elif cmd in ('s','status'):return 'status'
        elif cmd in ('h','help','?'):return 'help'
        else:raise ValueError('Unknown command; use n/p/seq N/play/pause/rate FPS/status/q')
        return 'backward' if self.position<old else 'forward' if self.position>old else 'unchanged'


class BagFrames:
    def __init__(self,index):
        import rosbag
        self.bag=rosbag.Bag(index['bag_path'],'r');self.index=index;self.cached=None
    def close(self):self.bag.close()
    def get(self,position):
        if self.cached and self.cached[0]==position:return self.cached[1]
        import rospy
        row=self.index['frames'][position];ns=row['record_stamp_ns'];topics=row.get('topics',self.index['topics'])
        start=rospy.Time(ns//10**9,ns%10**9)
        end=rospy.Time((ns+1)//10**9,(ns+1)%10**9)
        found={}
        for topic,msg,record in self.bag.read_messages(topics=topics,start_time=start,end_time=end):
            if record.to_nsec()!=ns:continue
            if topic in found:raise ValueError('Duplicate topic at source frame record time')
            if getattr(msg,'_type','')!='sensor_msgs/PointCloud2':raise ValueError('Only PointCloud2 debug messages accepted')
            if msg.header.seq!=row['seq'] or msg.header.stamp.to_nsec()!=row['header_stamp_ns']:
                raise ValueError('Source sequence/header does not match exact frame index')
            if not msg.header.frame_id:raise ValueError('Empty source frame_id')
            found[topic]=msg
        if set(found)!=set(topics):raise ValueError(f'Incomplete source frame topics: {set(topics)-set(found)}')
        if len({m.header.frame_id for m in found.values()})!=1:raise ValueError('Mixed frame_id in one source frame')
        self.cached=(position,found);return found


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index',required=True);p.add_argument('--seq',type=int)
    p.add_argument('--rate',type=float,default=10.);p.add_argument('--autoplay',action='store_true')
    p.add_argument('--refresh-hz',type=float,default=2.,help='Whole-frame wall-time refresh while paused; no latching')
    p.add_argument('--clock',action='store_true',help='Publish /clock with original record stamp; never alter message headers')
    p.add_argument('--commands',help='Non-TTY script: show,next,prev,seq:245847,play:0.5,pause,quit')
    p.add_argument('--command-delay',type=float,default=.2,help='Wall seconds after scripted non-play commands')
    p.add_argument('--once',action='store_true',help='Publish selected frame and hold briefly, then exit')
    p.add_argument('--hold-seconds',type=float,default=2.)
    p.add_argument('--selfcheck',action='store_true',help='Read/validate indexed bag frames only, do not create ROS node')
    p.add_argument('--log',default=str(V1C/'evidence/frame_review_events.jsonl'))
    args=p.parse_args();guard_environment()
    log=Path(args.log).resolve()
    if not under(log,V1C):p.error('All logs must remain under v1c')
    if not 0<=args.refresh_hz<=10 or not 0<=args.hold_seconds<=60 or not 0<=args.command_delay<=5:p.error('Invalid bounded refresh/hold')
    index=load_index(args.index);controller=FrameController(index['frames'],args.seq,args.rate)
    log.parent.mkdir(parents=True,exist_ok=True)
    import rospy
    store=BagFrames(index)
    with log.open('a') as output:
        def event(kind,**kwargs):
            row=dict(wall_time_ns=time.time_ns(),event=kind,**kwargs)
            output.write(json.dumps(row)+'\n');output.flush();print(json.dumps(row),flush=True)
        if args.selfcheck:
            try:
                for i,row in enumerate(index['frames']):
                    messages=store.get(i);event('selfcheck_frame',seq=row['seq'],topic_count=len(messages),
                     record_stamp_ns=row['record_stamp_ns'],header_stamp_ns=row['header_stamp_ns'])
                event('selfcheck_complete',frame_count=len(index['frames']),ros_node_created=False)
            finally:store.close()
            return
        from sensor_msgs.msg import PointCloud2
        from rosgraph_msgs.msg import Clock
        rospy.init_node('opdf_v1c_frame_review',anonymous=True,disable_signals=True)
        topics=sorted(set().union(*(set(f.get('topics',index['topics'])) for f in index['frames'])))
        pubs={t:rospy.Publisher(t,PointCloud2,queue_size=1,latch=False) for t in topics}
        clock_pub=rospy.Publisher('/clock',Clock,queue_size=1,latch=False) if args.clock else None
        if args.clock:rospy.set_param('/use_sim_time',True)
        last_record=None;batch=0
        def publish(position,reason):
            nonlocal last_record,batch
            row=index['frames'][position];messages=store.get(position) # validate all before any publish
            backward=last_record is not None and row['record_stamp_ns']<last_record
            if clock_pub:
                ns=row['record_stamp_ns'];clock_pub.publish(Clock(clock=rospy.Time(ns//10**9,ns%10**9)))
                event('clock',clock_ns=ns,source='original_record_stamp_ns',backward=backward,seq=row['seq'])
            if backward:
                # Empty clearing clouds contain no invented echo. They use the
                # target source header. RViz Decay Time 0 + queue 1 retains only
                # the current cloud. No fake monotonic time and no TF are sent.
                for topic,msg in messages.items():
                    empty=copy.deepcopy(msg);empty.height=1;empty.width=0;empty.row_step=0;empty.data=b''
                    pubs[topic].publish(source_header_message(empty))
                time.sleep(.05) # wall sleep works after a backward /clock jump
                event('backward_cache_clear',seq=row['seq'],record_stamp_ns=row['record_stamp_ns'],
                      empty_clouds=len(messages),header_stamp_ns=row['header_stamp_ns'])
            batch+=1
            event('frame_begin',batch=batch,seq=row['seq'],reason=reason,position=position,
                  header_stamp_ns=row['header_stamp_ns'],record_stamp_ns=row['record_stamp_ns'])
            for topic in topics:
                if topic in messages:pubs[topic].publish(source_header_message(messages[topic]))
            event('frame_complete',batch=batch,seq=row['seq'],topics=list(messages),
                  counts={t:m.width*m.height for t,m in messages.items()},network_atomic=False,
                  header_serialization_policy='local_PointCloud2_subclass_skips_rospy_transport_seq_rewrite',
                  record_stamp_ns=row['record_stamp_ns'],header_stamp_ns=row['header_stamp_ns'],
                  topic_headers={t:dict(seq=m.header.seq,stamp_ns=m.header.stamp.to_nsec(),frame_id=m.header.frame_id) for t,m in messages.items()})
            last_record=row['record_stamp_ns']
        try:
            time.sleep(.8);publish(controller.position,'initial')
            controller.playing=args.autoplay;last=time.monotonic();started=last
            script=args.commands.split(',') if args.commands else None;next_command=last
            print('Commands + Enter: n / p / seq N / play / pause / rate FPS / status / q',flush=True)
            while not rospy.is_shutdown():
                now=time.monotonic()
                if args.once and now-started>=args.hold_seconds:break
                if controller.playing and now-last>=1/controller.rate:
                    old=controller.position;controller.command('n')
                    if controller.position==old:controller.playing=False
                    else:publish(controller.position,'autoplay')
                    last=now
                elif not controller.playing and args.refresh_hz and now-last>=1/args.refresh_hz:
                    publish(controller.position,'paused_refresh');last=now
                line=None;command_hold=args.command_delay
                if not args.once and script is not None and now>=next_command:
                    if not script:break
                    token=script.pop(0).strip()
                    if token.startswith('play:'):
                        command_hold=float(token.split(':',1)[1])
                        if not 0<=command_hold<=30:raise ValueError('Scripted play duration must be 0..30 wall seconds')
                        line='play'
                    else:line=token.replace(':',' ',1)
                    next_command=now+command_hold
                elif not args.once and script is None and select.select([sys.stdin],[],[],.03)[0]:
                    line=sys.stdin.readline()
                    if not line:break
                if line is not None:
                    try:
                        action=controller.command(line)
                        if action=='quit':break
                        if action in ('backward','forward','unchanged'):
                            controller.playing=False;publish(controller.position,action);last=time.monotonic()
                        else:event('command',action=action,seq=controller.frames[controller.position]['seq'],
                                   rate_fps=controller.rate,playing=controller.playing)
                    except (ValueError,KeyError) as exc:event('command_error',error=str(exc))
                else:time.sleep(.01)
        except KeyboardInterrupt:pass
        finally:
            store.close();event('closed',published_batches=batch,gui_verified=False)
            rospy.signal_shutdown('bounded debug review completed')


if __name__=='__main__':main()
