"""Diagnostics must reconstruct the frozen rule and respect overlap/unavailability."""
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
import pytest
import yaml

C=Path(__file__).resolve().parents[1];B=C.parent
sys.dont_write_bytecode=True
sys.path[:0]=[str(C),str(B)]
from opdf_c.gate_diagnostics import reconstruct_gates,check_reconstruction,counterfactuals,statistics
from opdf.decision import classify

def evidence():
    n=7
    a={'xyz':np.array([[8.,0.,0.]]*n),'raw_slot_id':np.arange(n,dtype=np.uint64),
       'valid_xyz_mask':np.ones(n,bool),'intensity':np.ones(n)*3,
       'ground__ground_available':np.ones(n,bool),'ground__ground_mask':np.zeros(n,bool),
       'ground__low_object_mask':np.zeros(n,bool),'ground__near_ground_mask':np.zeros(n,bool),
       'ground__ground_height':np.ones(n),
       'optical__optical_available':np.ones(n,bool),'optical__optical_weak_score':np.ones(n)*.8,
       'optical__relative_intensity_z':np.ones(n)*-1.2,'optical__local_intensity_median':np.ones(n)*5,
       'geometry__scan_available':np.ones(n,bool),'geometry__spatial_available':np.ones(n,bool),
       'geometry__scan_surface_score':np.ones(n)*.2,'geometry__scan_discontinuity_score':np.ones(n)*.8,
       'geometry__spatial_surface_score':np.ones(n)*.2,'geometry__spatial_diffuse_score':np.ones(n)*.8,
       'geometry__edge_protect_mask':np.zeros(n,bool),'geometry__spatial_neighbor_count':np.ones(n)*12,
       'geometry__linearity':np.ones(n)*.2,'geometry__planarity':np.ones(n)*.2}
    a['ground__low_object_mask'][1]=True;a['ground__near_ground_mask'][1]=True
    a['geometry__edge_protect_mask'][2]=True
    a['optical__optical_available'][3]=False
    a['optical__optical_weak_score'][4]=.5
    a['ground__ground_available'][5]=False
    a['xyz'][6]=np.nan;a['valid_xyz_mask'][6]=False
    cfg=yaml.safe_load((B/'configs/v1b.yaml').read_text())
    ev=lambda prefix:{'arrays':{k.split('__',1)[1]:v for k,v in a.items() if k.startswith(prefix+'__')}}
    f=SimpleNamespace(xyz=a['xyz'],valid_xyz_mask=a['valid_xyz_mask'])
    a.update(classify(f,ev('ground'),ev('optical'),ev('geometry'),cfg)['arrays'])
    return a,cfg

def test_exact_rule_reconstruction_including_invalid_and_unavailable():
    a,cfg=evidence();g=reconstruct_gates(a,cfg)
    assert check_reconstruction(a,g)['exact_match']
    assert a['labels'].tolist()==[2,3,3,3,3,3,0]

def test_overlapping_low_and_near_do_not_add_two_fake_removals():
    a,cfg=evidence();g=reconstruct_gates(a,cfg);cf=counterfactuals(a,g,cfg)
    assert not cf['remove_near_A_protection']['added'].any()
    assert not cf['remove_low_A_protection']['added'].any()
    assert np.flatnonzero(cf['remove_edge_A_protection']['added']).tolist()==[2]

def test_one_threshold_counterfactual_and_missing_reference_are_separate():
    a,cfg=evidence();g=reconstruct_gates(a,cfg);cf=counterfactuals(a,g,cfg)
    assert np.flatnonzero(cf['optical_threshold_minus_0p10']['added']).tolist()==[4]
    assert np.flatnonzero(cf['remove_ground_available_requirement']['added']).tolist()==[5]
    assert not any(v['removed'].any() for v in cf.values())

def test_unavailable_is_not_counted_as_available_threshold_failure():
    a,cfg=evidence();g=reconstruct_gates(a,cfg);r=statistics(a,g,counterfactuals(a,g,cfg),np.ones(7,bool))
    assert r['valid_nonG']==6
    o=r['gates']['optical'];assert o['available']==5 and o['unavailable']==1 and o['pass']==4 and o['fail_when_available']==1
    assert sum(r['availability_pattern_OSP'].values())==6

def test_duplicate_source_slots_rejected_and_corrupted_stored_rule_detected():
    a,cfg=evidence();g=reconstruct_gates(a,cfg);a['labels'][0]=3
    assert not check_reconstruction(a,g)['exact_match']
    a['raw_slot_id'][1]=a['raw_slot_id'][0]
    with pytest.raises(ValueError,match='Duplicate'):reconstruct_gates(a,cfg)
