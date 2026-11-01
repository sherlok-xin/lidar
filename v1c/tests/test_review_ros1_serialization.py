"""Real Noetic wire-serialization regression, no ROS node or master needed.

Run in sourced Noetic: python3 -B this_file --index ... --output ...
Pytest on the host skips the real check when ROS1 is unavailable.
"""
import argparse
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode=True
V1C=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('player_source_header_regression',V1C/'scripts/frame_review_ros1.py')
player=importlib.util.module_from_spec(spec);spec.loader.exec_module(player)


def payload(msg):
    b=io.BytesIO();msg.serialize(b);return b.getvalue()


def check_real(index_path,output_path,seq=245847):
    import inspect
    import rospy.msg
    from sensor_msgs.msg import PointCloud2
    index=player.load_index(index_path)
    position=next(i for i,row in enumerate(index['frames']) if row['seq']==seq)
    store=player.BagFrames(index)
    original_class_flag=PointCloud2._has_header
    serializer_before=rospy.msg.serialize_message
    rows=[]
    try:
        messages=store.get(position)
        for topic,message in messages.items():
            expected=payload(message);original_seq=message.header.seq
            safe=player.source_header_message(message)
            converted=rospy.msg.args_kwds_to_message(PointCloud2,(safe,),{})
            assert converted is safe
            b=io.BytesIO();rospy.msg.serialize_message(b,987654321,converted)
            wire=b.getvalue();length=struct.unpack('<I',wire[:4])[0]
            restored=PointCloud2().deserialize(wire[4:])
            assert wire[4:]==expected and length==len(expected)
            assert restored.header.seq==original_seq and safe.header.seq==original_seq and message.header.seq==original_seq
            assert safe._type==PointCloud2._type and safe._md5sum==PointCloud2._md5sum
            assert safe._slot_types==PointCloud2._slot_types
            assert PointCloud2._has_header==original_class_flag and rospy.msg.serialize_message is serializer_before
            # Negative control: this exact installed rospy changes a normal
            # PointCloud2 header, proving the regression exercises the bug.
            negative=PointCloud2().deserialize(expected);bad=io.BytesIO()
            rospy.msg.serialize_message(bad,123,negative)
            assert negative.header.seq==123 and bad.getvalue()[4:]!=expected
            rows.append(dict(topic=topic,source_seq=original_seq,transport_counter=987654321,
                received_seq=restored.header.seq,frame_id=restored.header.frame_id,
                header_stamp_ns=restored.header.stamp.to_nsec(),type=safe._type,md5sum=safe._md5sum,
                serialized_bytes=len(expected),payload_sha256=hashlib.sha256(expected).hexdigest(),
                exact_original_wire_payload=True,argument_converter_preserves_subclass=True,
                original_cached_header_unchanged=True,negative_control_seq_rewritten=True))
    finally:store.close()
    result=dict(status='PASS',scope='actual Noetic rospy serializer + args conversion; no ROS node/pubsub/GUI',
                index=str(Path(index_path).resolve()),selected_source_seq=seq,topics_tested=len(rows),
                base_pointcloud_has_header_unchanged=PointCloud2._has_header==original_class_flag,
                global_serializer_unchanged=rospy.msg.serialize_message is serializer_before,
                serializer_file=inspect.getsourcefile(rospy.msg.serialize_message),
                serializer_source=inspect.getsource(rospy.msg.serialize_message),
                argument_converter_source=inspect.getsource(rospy.msg.args_kwds_to_message),results=rows)
    output=Path(output_path).resolve()
    if not player.under(output,V1C):raise ValueError('All evidence stays in v1c')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2))
    return result


def test_real_noetic_serializer_preserves_source_seq(tmp_path):
    import pytest
    pytest.importorskip('rospy.msg')
    index=V1C/'outputs/v1b_continuous30/debug_frame_index.json'
    if not index.exists():pytest.skip('Real exported debug bag unavailable')
    check=check_real(index,tmp_path/'real_serialization.json')
    assert check['status']=='PASS' and check['topics_tested']>=8


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index',required=True);p.add_argument('--output',required=True);p.add_argument('--seq',type=int,default=245847)
    a=p.parse_args();r=check_real(a.index,a.output,a.seq)
    print(json.dumps({k:v for k,v in r.items() if k not in ('results','serializer_source','argument_converter_source')},indent=2))
