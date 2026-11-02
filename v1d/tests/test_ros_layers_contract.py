"""Lossless debug layer tests on approved cached frames; no source bag reads."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import importlib.util,json
import numpy as np
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from opdf_d.ros_layers import load_frame,guard_masks,load_npz,TOPICS,DTYPE,pack,evidence_change


def entry(seq):
    m=json.loads((ROOT/'outputs/d1_ground/input_manifest.json').read_text())
    return next(r for r in m['frames']if r['seq']==seq)


def load(seq,guard=True):
    return load_frame(ROOT/'outputs/d1_ground/frames',entry(seq),ROOT.parent/'v1c/outputs/v1c_uniform_pair',
        ROOT/'outputs/d1_pointwise_guard/frames'if guard else None,ROOT/'outputs/d1_ground'if guard else None)


def test_missing_guard_never_suppresses_candidates():
    arrays,layers,meta=load(245846,False)
    strict=arrays['d1__nonground_strict_mask']
    assert meta['diagnostics']['guard_status']=='GUARD_UNAVAILABLE_NO_SUPPRESSION'
    assert meta['diagnostics']['candidate_clutter_count']>0
    assert np.array_equal(layers['/opdf_v1/nonground_display_only']['raw_slot_id'],arrays['raw_slot_id'][strict])


@pytest.mark.parametrize('seq,slot',[(245846,84249),(245858,84182)])
def test_known_unavailable_slots_deferred_and_retained(seq,slot):
    arrays,layers,meta=load(seq)
    assert arrays['d1__low_clutter_mask'][slot]
    assert slot in layers['/opdf_v1/nonground_display_only']['raw_slot_id']
    assert slot in layers['/opdf_v1/low_clutter_candidate']['raw_slot_id']
    assert meta['diagnostics']['guard_status']=='SOURCE_VERIFIED_POINTWISE_GUARD'
    assert set(layers)==set(TOPICS)-{'/opdf_v1/raw'}
    assert len(TOPICS)==23
    assert np.array_equal(layers['/opdf_v1/retained']['raw_slot_id'],arrays['raw_slot_id'][arrays['valid_xyz_mask']&np.isin(arrays['labels'],[1,3])])
    for points in layers.values():
        assert points.dtype==DTYPE
        ids=points['raw_slot_id']
        for col,k in enumerate(('x','y','z')):
            assert points[k].tobytes()==np.asarray(arrays['xyz'][ids,col],dtype='<f4').tobytes()
        assert points['intensity'].tobytes()==np.asarray(arrays['intensity'][ids],dtype='<f4').tobytes()


def test_explicit_malformed_guard_rejected():
    arrays,_,_=load(245847,False)
    with pytest.raises(ValueError,match='Missing/malformed'):
        guard_masks(arrays,{})
    wrong={'low_clutter_suppressible_mask':arrays['d1__nonground_strict_mask'],
           'low_clutter_deferred_mask':np.zeros(len(arrays['xyz']),bool),
           'nonground_guarded_display_mask':np.zeros(len(arrays['xyz']),bool)}
    with pytest.raises(ValueError,match='partition'):guard_masks(arrays,wrong)


def test_guard_hash_mismatch_rejected(tmp_path):
    d=ROOT/'outputs/d1_pointwise_guard/frames';seq=245847;k='seq'+str(seq)
    (tmp_path/(k+'.npz')).write_bytes((d/(k+'.npz')).read_bytes())
    meta=json.loads((d/(k+'.json')).read_text());meta['source_d1_npz_sha256']='0'*64
    (tmp_path/(k+'.json')).write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='SHA mismatch'):
        load_frame(ROOT/'outputs/d1_ground/frames',entry(seq),ROOT.parent/'v1c/outputs/v1c_uniform_pair',tmp_path,ROOT/'outputs/d1_ground')


def test_label_change_does_not_require_score_availability():
    a={'xyz':np.ones((4,3),np.float32),'intensity':np.ones(4,np.float32),'valid_xyz_mask':np.ones(4,bool),
       'raw_slot_id':np.arange(4,dtype=np.uint32),'labels':np.array([3,2,1,3]),'b__labels':np.array([1,3,3,2]),
       'score_e':np.zeros(4,np.float32),'score_a':np.zeros(4,np.float32),
       'b__score_e':np.zeros(4,np.float32),'b__score_a':np.zeros(4,np.float32),
       'available_e':np.zeros(4,bool),'available_a':np.zeros(4,bool)}
    e,ed=evidence_change(a,'e');p,ad=evidence_change(a,'a')
    assert e['raw_slot_id'].tolist()==[0,2]
    assert p['raw_slot_id'].tolist()==[1,3]
    assert ed['physical_loss_or_correctness_not_inferred']
    assert ad['score_increase']==0
