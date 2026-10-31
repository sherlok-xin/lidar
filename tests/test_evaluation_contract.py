"""Synthetic unit contracts only; no invented real-world GT performance."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from opdf.evaluation import frame_metrics, validate_reference_labels, write_run_report
from opdf.visualization import load_result, select_slots, render_frame

spec = importlib.util.spec_from_file_location('review_roi', ROOT/'scripts/review_roi.py')
review = importlib.util.module_from_spec(spec); spec.loader.exec_module(review)
spec2 = importlib.util.spec_from_file_location('publish_rviz', ROOT/'scripts/publish_rviz.py')
rviz = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(rviz)


@pytest.fixture
def result(tmp_path):
    path=tmp_path/'fixture.npz'
    xyz=np.array([[0,0,0],[1,2,3],[2,0,1],[4,0,0],[np.nan,0,0]],np.float32)
    np.savez(path,xyz=xyz,intensity=np.arange(5,dtype=np.float32),valid_xyz_mask=np.array([1,1,1,1,0],bool),
             raw_slot_id=np.array([42,3,80,9,25],np.uint64),labels=np.array([1,2,3,4,0],np.uint8),
             score_e=np.array([1,.1,np.nan,.2,np.nan],np.float32),score_a=np.array([.1,.8,np.nan,.1,np.nan],np.float32),
             available_e=np.array([1,1,0,1,0],bool),available_a=np.array([1,1,0,1,0],bool),
             reason_code=np.array([1,2,4,8,0],np.uint32),geometry__test_feature=np.arange(10).reshape(5,2))
    path.with_suffix('.json').write_text(json.dumps({'status':'OK','metadata':{'raw_message_sha256':'a'*64,
        'frame_id':'fixture','header_stamp_ns':1234000000000},'diagnostics':{'timings_ms':{'fixture':1.2}}}))
    return path


def test_unlabeled_denominators_and_empty_bands(result):
    m=frame_metrics(result)
    assert m['valid_xyz_count']==4 and m['invalid_xyz_count']==1
    assert all(m[f'{x}_candidate_rate_of_valid']==.25 for x in 'eaug')
    assert m['protected_e_u_count']==2 and m['a_score_unavailable_count']==1
    assert m['range_50_inf_a_candidate_rate'] is None
    assert m['invalid_label_mismatch_count']==0 and m['timing_ms_fixture']==1.2
    assert not any(k in m for k in ('accuracy','precision','recall','f1'))


def test_abstain_retains_unknown_and_zero_available(result):
    a=load_result(result); a['labels']=np.array([3,3,3,3,0],np.uint8)
    a['available_a'][:]=False;a['available_e'][:]=False
    np.savez(result,**a)
    m=frame_metrics(result,{'status':'ABSTAIN'})
    assert m['status']=='ABSTAIN' and m['u_candidate_count']==4
    assert m['a_candidate_count']==0 and m['a_score_unavailable_count']==4


def test_exact_roi_not_display_cap_and_invalid_slot_diagnostic(result):
    a=load_result(result)
    assert select_slots(a,[-1,2,-1,3,-1,4]).tolist()==[0,1,2]
    assert review.exact_selection(a,{'raw_slot_ids':[80,42]}).tolist()==[0,2]
    assert review.exact_selection(a,{'raw_slot_ids':[25]}).tolist()==[4]
    with pytest.raises(ValueError):review.exact_selection(a,{'raw_slot_ids':[999]})
    with pytest.raises(ValueError):select_slots(a,[2,1,0,1,0,1])


def test_shared_3d_render_deterministic_sample_and_html(result,tmp_path):
    view={'version':1,'target':[1,1,1],'distance':10,'azimuth_deg':-50,'elevation_deg':25,'fov_deg':45,'projection':'perspective','up_axis':'z'}
    r=render_frame(result,output_png=tmp_path/'four.png',output_html=tmp_path/'four.html',view=view,max_points=3)
    assert r['finite_roi_count']==4 and r['selected_count']==3
    assert r['selected_raw_slot_ids']==[3,9,80]
    assert r['camera']==view
    text=(tmp_path/'four.html').read_text()
    data=json.loads(text.split('<script id="opdf-data" type="application/json">')[1].split('</script>')[0])
    assert data['ids']==r['selected_raw_slot_ids'] and len(data['xyz'])==3
    assert 'points.sort((a,b)=>b.depth-a.depth)' in text and 'state.camera' in text
    assert text.count('<canvas id=')==4 and 'https://' not in text and 'http://' not in text
    assert (tmp_path/'four.png').stat().st_size>10000


def test_blind_review_does_not_embed_hidden_answers(result,tmp_path):
    out=tmp_path/'blind'
    case=review.export_review(result,out,roi={'raw_slot_ids':[42,3,25]},blind=True,max_points=1)
    assert case['exact_selected_count']==3 and case['selected_invalid_xyz_count']==1
    assert np.load(out/'raw_slot_ids.npy').tolist()==[3,25,42]
    with np.load(out/'exact_slots.npz') as z:
        assert set(z.files)=={'xyz','intensity','valid_xyz_mask','raw_slot_id'}
    text=(out/'review.html').read_text()
    data=json.loads(text.split('<script id="opdf-data" type="application/json">')[1].split('</script>')[0])
    assert data['blind'] and not {'labels','score_a','score_e','reason_code'} & set(data)
    human=json.loads((out/'human_review.json').read_text())
    assert human['reviewer_id'] is None and human['confidence'] is None and human['human_label'] is None
    assert human['status']=='PENDING_HUMAN_REVIEW'


def test_unblind_roi_exports_every_aligned_feature(result,tmp_path):
    out=tmp_path/'review'
    review.export_review(result,out,roi={'raw_slot_ids':[42,80]},max_points=1)
    with np.load(out/'exact_slots.npz') as z:
        assert 'geometry__test_feature' in z.files and z['raw_slot_id'].tolist()==[42,80]
        assert z['geometry__test_feature'].tolist()==[[0,1],[4,5]]
    with pytest.raises(ValueError):review.export_review(result,tmp_path/'invalid',human_label='A')


def test_l2_reference_requires_true_source_message_identity(result,tmp_path):
    ref={'source_message_sha256':'b'*64,'source_npz_sha256':hashlib.sha256(result.read_bytes()).hexdigest(),
         'reviewer_id':'SYNTHETIC_TEST_ONLY','annotation_version':'fixture','provenance':'synthetic fixture',
         'independent':True,'annotations':[{'raw_slot_id':42,'label':'U'}]}
    p=tmp_path/'ref.json';p.write_text(json.dumps(ref))
    with pytest.raises(ValueError,match='source message'):validate_reference_labels(result,p)
    ref['source_message_sha256']='a'*64;p.write_text(json.dumps(ref))
    check=validate_reference_labels(result,p)
    assert check['unannotated_valid_slots']==3 and not check['performance_computed']
    ref['annotations'].append({'raw_slot_id':25,'label':'E'});p.write_text(json.dumps(ref))
    with pytest.raises(ValueError):validate_reference_labels(result,p)


def test_rviz_guard_is_explicit_and_local(monkeypatch):
    monkeypatch.delenv('ROS_LOCALHOST_ONLY',raising=False)
    with pytest.raises(ValueError):rviz.guard_domain(198)
    monkeypatch.setenv('ROS_LOCALHOST_ONLY','1');monkeypatch.setenv('ROS_DOMAIN_ID','198')
    rviz.guard_domain(198)
    with pytest.raises(ValueError):rviz.guard_domain(0)
    with pytest.raises(ValueError):rviz.guard_domain(199)
