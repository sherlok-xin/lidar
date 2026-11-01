"""Software contracts, using synthetic fixtures rather than material truth."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


player=load('v1c_frame_player','frame_review_ros1.py')
review=load('v1c_review_compare','review_compare.py')


def frames():
    return [dict(seq=245847+i,header_stamp_ns=1000000000+i*100000000,
                 record_stamp_ns=1010000000+i*100000000,topics=list(player.PRIMARY)) for i in range(3)]


def test_navigation_real_seq_order_and_no_stamp_invention():
    original=frames();c=player.FrameController(original,start_seq=245848,rate=10)
    assert c.command('next')=='forward' and c.frames[c.position]['seq']==245849
    assert c.command('prev')=='backward' and c.frames[c.position]['record_stamp_ns']==1110000000
    assert c.command('seq 245847')=='backward'
    assert c.command('show')=='unchanged'
    c.command('rate 2');c.command('play');assert c.playing and c.rate==2
    c.command('pause');assert not c.playing
    with pytest.raises(ValueError):c.command('seq 245850')
    with pytest.raises(ValueError):c.command('rate 0')
    assert original==frames()


def test_master_guard_and_index_forbid_control_topics(tmp_path,monkeypatch):
    monkeypatch.setenv('ROS_MASTER_URI','http://127.0.0.1:11311')
    with pytest.raises(ValueError,match='production'):player.guard_environment()
    monkeypatch.setenv('ROS_MASTER_URI','http://127.0.0.1:11321');monkeypatch.setenv('ROS_IP','127.0.0.1')
    monkeypatch.setenv('ROS_LOG_DIR',str(tmp_path/'ros_logs'));monkeypatch.delenv('ROS_HOSTNAME',raising=False)
    player.guard_environment()
    p=tmp_path/'index.json';index=dict(bag_path='dummy.bag',topics=list(player.PRIMARY),frames=frames())
    p.write_text(json.dumps(index));assert len(player.load_index(p)['frames'])==3
    index['frames'][0]['topics'].append('/vehicle/brake');p.write_text(json.dumps(index))
    with pytest.raises(ValueError):player.load_index(p)


def test_all_topics_validated_before_returning_source_frame(monkeypatch):
    class Time:
        def __init__(self,s,n):self.ns=s*10**9+n
        def to_nsec(self):return self.ns
    row=frames()[0];items=[]
    for t in player.PRIMARY:
        msg=SimpleNamespace(_type='sensor_msgs/PointCloud2',header=SimpleNamespace(seq=row['seq'],
             stamp=Time(1,0),frame_id='rslidar'))
        items.append((t,msg,Time(1,10000000)))
    fake=SimpleNamespace(read_messages=lambda **kw:iter(items),close=lambda:None)
    monkeypatch.setitem(sys.modules,'rosbag',SimpleNamespace(Bag=lambda *a:fake))
    monkeypatch.setitem(sys.modules,'rospy',SimpleNamespace(Time=Time))
    store=player.BagFrames(dict(bag_path='dummy',topics=list(player.PRIMARY),frames=[row]))
    assert set(store.get(0))==set(player.PRIMARY)
    items.pop();store.cached=None
    with pytest.raises(ValueError,match='Incomplete'):store.get(0)


def test_rviz_configuration_keeps_layers_separate():
    config=yaml.safe_load((ROOT/'configs/opdf_debug_ros1.rviz').read_text())
    manager=config['Visualization Manager'];assert manager['Global Options']['Fixed Frame']=='rslidar'
    clouds=[d for d in manager['Displays'] if d['Class']=='rviz/PointCloud2']
    assert sum(d['Enabled'] for d in clouds)==1
    assert all(d['Decay Time']==0 and d['Queue Size']==1 for d in clouds)
    assert next(d for d in clouds if d['Enabled'])['Topic']=='/opdf_v1/raw'
    assert not any('solid' in d['Topic'] for d in clouds)


def arrays():
    return dict(xyz=np.array([[1,2,3],[4,5,6],[np.nan,0,0]],np.float32),
       intensity=np.array([3,4,0],np.float32),raw_slot_id=np.arange(3,dtype=np.uint64),
       valid_xyz_mask=np.array([1,1,0],bool),labels=np.array([1,3,0],np.uint8),
       reason_code=np.array([2,4,0],np.uint32),score_e=np.zeros(3),score_a=np.zeros(3),
       available_e=np.array([1,0,0],bool),available_a=np.zeros(3,bool))


def test_exact_b_c_change_and_suspect_is_additive():
    b=arrays();c={k:v.copy() for k,v in b.items()};c['aerosol_suspect']=np.array([1,1,0],bool)
    r=review.compare_arrays(b,c,[0,1,2])
    assert r['changed_label_count']==0 and r['C_additive_suspect_counts']['aerosol_suspect']==2
    c['labels'][0]=2;r=review.compare_arrays(b,c,[0,1])
    assert r['transitions']['E->A']==1 and r['changed_label_count']==1
    c['raw_slot_id']=np.array([1,0,2],np.uint64)
    with pytest.raises(ValueError,match='domain'):review.compare_arrays(b,c,[0,1])


def test_manifest_source_identity_and_pending_human_review(tmp_path):
    result=tmp_path/'frames';result.mkdir();a=arrays();np.savez(result/'seq7.npz',**a)
    meta=dict(metadata=dict(seq=7,raw_message_sha256='a'*64,header_stamp_ns=1,record_stamp_ns=2,frame_id='fixture'))
    (result/'seq7.json').write_text(json.dumps(meta))
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(dict(frames=[dict(seq=7,sha256='a'*64,header_stamp_ns=1,record_stamp_ns=2)])))
    path,entry,_=review.locate_result(manifest,7,result);assert path.name=='seq7.npz'
    case=review.export_comparison(manifest,7,result,tmp_path/'case',roi={'raw_slot_ids':[0,1]},blind=True,max_points=2)
    observation=json.loads((tmp_path/'case/human_observation.json').read_text())
    assert all(observation[k] is None for k in ('reviewer_id','confidence','observation','whole_roi_semantic_label'))
    assert observation['status']=='PENDING_HUMAN_REVIEW'
    assert json.loads((tmp_path/'case/comparison.json').read_text())['status']=='BLIND_COMPARISON_DEFERRED'
    meta['metadata']['raw_message_sha256']='b'*64;(result/'seq7.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='SHA'):review.locate_result(manifest,7,result)
