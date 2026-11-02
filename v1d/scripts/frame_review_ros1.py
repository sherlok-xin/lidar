#!/usr/bin/env python3
"""V1-D path/topic/master adapter around the frozen V1-C frame-review engine."""
import importlib.util
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
sys.dont_write_bytecode=True
D=Path(__file__).resolve().parents[1]
SOURCE=D.parent/'v1c/scripts/frame_review_ros1.py'
spec=importlib.util.spec_from_file_location('frozen_c_frame_player',SOURCE)
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
EXTRA=tuple('/opdf_v1/'+x for x in ('ground_core','low_clutter_candidate','nonground_strict',
    'nonground_display_only','b_entity','b_aerosol','entity_evidence_change',
    'aerosol_evidence_change','hard_structure_protect','low_risk_unknown'))

def guard_environment():
    os.environ.setdefault('ROS_MASTER_URI','http://127.0.0.1:11331')
    os.environ.setdefault('ROS_IP','127.0.0.1')
    os.environ.setdefault('ROS_LOG_DIR',str(D/'evidence/ros_logs'))
    uri=urlparse(os.environ['ROS_MASTER_URI'])
    if uri.scheme!='http' or uri.hostname not in ('127.0.0.1','localhost') or uri.port!=11331:
        raise ValueError('V1-D requires its own loopback master :11331; existing :11321 is preserved')
    if os.environ.get('ROS_IP')!='127.0.0.1' or os.environ.get('ROS_HOSTNAME')not in (None,'','localhost','127.0.0.1'):
        raise ValueError('Loopback ROS_IP/ROS_HOSTNAME required')
    logs=Path(os.environ['ROS_LOG_DIR']).resolve()
    try:logs.relative_to(D)
    except ValueError:raise ValueError('All D logs must remain inside v1d')
    logs.mkdir(parents=True,exist_ok=True)

engine.V1C=D # Runtime destination, not a write to the frozen source file.
engine.MASTER='http://127.0.0.1:11331'
engine.ALLOWED.update(EXTRA)
engine.guard_environment=guard_environment
FrameController=engine.FrameController
BagFrames=engine.BagFrames
source_header_message=engine.source_header_message
load_index=engine.load_index
if __name__=='__main__':engine.main()
