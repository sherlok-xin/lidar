"""D reuses C navigation but must never attach to the active C master."""
import importlib.util,json,os
from pathlib import Path
import pytest
D=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('test_d_frame_adapter',D/'scripts/frame_review_ros1.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def test_d_guard_rejects_user_c_master(monkeypatch,tmp_path):
    monkeypatch.setenv('ROS_MASTER_URI','http://127.0.0.1:11321')
    monkeypatch.setenv('ROS_IP','127.0.0.1');monkeypatch.delenv('ROS_HOSTNAME',raising=False)
    monkeypatch.setenv('ROS_LOG_DIR',str(tmp_path/'logs'))
    with pytest.raises(ValueError,match='11331'):m.guard_environment()

def test_d_guard_accepts_only_d_log_scope(monkeypatch,tmp_path):
    monkeypatch.setenv('ROS_MASTER_URI','http://127.0.0.1:11331')
    monkeypatch.setenv('ROS_IP','127.0.0.1');monkeypatch.delenv('ROS_HOSTNAME',raising=False)
    monkeypatch.setenv('ROS_LOG_DIR',str(tmp_path/'logs'));m.guard_environment()
    monkeypatch.setenv('ROS_LOG_DIR',str(D.parent/'v1c/evidence/ros_logs'))
    with pytest.raises(ValueError,match='v1d'):m.guard_environment()

def test_original_controller_keeps_source_time_and_navigation():
    rows=[dict(seq=7,header_stamp_ns=11,record_stamp_ns=15),dict(seq=8,header_stamp_ns=21,record_stamp_ns=25)]
    c=m.FrameController(rows,start_seq=8)
    assert c.command('p')=='backward' and c.frames[c.position]['record_stamp_ns']==15
    assert c.command('seq 8')=='forward' and c.frames[c.position]['header_stamp_ns']==21
    assert '/opdf_v1/nonground_display_only' in m.engine.ALLOWED
    assert '/cmd_vel' not in m.engine.ALLOWED and m.engine.V1C==D
