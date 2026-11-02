"""Synthetic contract tests, not material annotations or model performance."""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from opdf_d.visualization import render_d1_views,mask_array
spec=importlib.util.spec_from_file_location('review_d_test',ROOT/'scripts/review_d.py')
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)


def arrays():
    a=dict(xyz=np.array([[0,0,0],[1,2,3],[2,1,0],[4,0,0],[np.nan,0,0]],np.float32),
       intensity=np.arange(5,dtype=np.float32),raw_slot_id=np.arange(5,dtype=np.uint64),
       valid_xyz_mask=np.array([1,1,1,1,0],bool),labels=np.array([1,2,3,4,0],np.uint8),
       reason_code=np.arange(5,dtype=np.uint32),score_e=np.zeros(5),score_a=np.zeros(5),
       available_e=np.ones(5,bool),available_a=np.ones(5,bool))
    for name,values in {'ground_core_mask':[1,0,0,0,0],'low_clutter_mask':[0,0,1,0,0],
        'nonground_strict_mask':[0,1,0,1,0],'nonground_display_mask':[0,1,1,1,0],
        'ground_available':[1,1,1,1,0],'hard_structure_protect_mask':[0,1,0,0,0]}.items():
        a['d1__'+name]=np.array(values,bool)
    a['d1__local_height']=np.array([0,3,.2,.1,np.nan],np.float32)
    return a


def test_d1_shared_sample_full_counts_and_ground_semantics(tmp_path):
    p=tmp_path/'seq7.npz';a=arrays();np.savez(p,**a)
    r=render_d1_views(p,output_png=tmp_path/'views.png',max_points=2)
    assert r['finite_roi_count']==4 and r['display_sample_count']==2
    assert r['full_roi_counts']=={'RAW':4,'GroundCore':1,'LowClutter':1,'NongroundStrict':2,'NongroundDisplay':3}
    assert r['labels_G_roi_count']==1 and r['hard_structure_protect_roi_count']==1
    assert not r['performance_computed']
    with np.load(p) as z:assert np.array_equal(z['labels'],a['labels'])
    a['d1__ground_core_mask']=np.arange(5)
    with pytest.raises(ValueError):mask_array(a,'ground_core_mask')


def test_exact_domain_rejects_coordinate_substitution():
    a=arrays();b={k:v.copy() for k,v in a.items()};review.domain(a,b)
    b['xyz'][1,0]+=.001
    with pytest.raises(ValueError,match='xyz'):review.domain(a,b)


def fixture_sources(tmp_path):
    frames=tmp_path/'frames';frames.mkdir();rows=[]
    for seq in (6,7,8):
        p=frames/f'seq{seq}.npz';np.savez(p,**arrays())
        entry=dict(key=f'seq{seq}',seq=seq,header_stamp_ns=1000+seq,record_stamp_ns=2000+seq,sha256=str(seq)*64)
        p.with_suffix('.json').write_text(json.dumps({'metadata':dict(seq=seq,header_stamp_ns=1000+seq,
             record_stamp_ns=2000+seq,raw_message_sha256=str(seq)*64,frame_id='synthetic_fixture')}))
        rows.append(entry)
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'frames':rows}))
    return frames,manifest


def test_raw_neighbor_review_hides_answers_preserves_features(tmp_path):
    frames,manifest=fixture_sources(tmp_path)
    case=review.export_raw_case(manifest,frames,7,tmp_path/'raw_case',roi={'bbox':[-1,5,-1,5,-1,5]},max_points=2)
    assert case['context_sequences']==[6,7,8] and not case['ground_truth']
    h=json.loads((tmp_path/'raw_case/human_review.json').read_text())
    assert all(h[k] is None for k in ('reviewer_id','confidence','observation','point_annotations','instance_annotations'))
    with np.load(tmp_path/'raw_case/blind_raw/seq7_raw.npz') as z:
        assert set(z.files)=={'xyz','intensity','valid_xyz_mask','raw_slot_id'}
        assert len(z['xyz'])==4
    with np.load(tmp_path/'raw_case/algorithm_evidence_unblinded/seq7_all_features.npz') as z:
        assert 'labels' in z.files and 'd1__local_height' in z.files
    html=(tmp_path/'raw_case/blind_raw/raw_neighbors_frames/seq7.html').read_text()
    payload=json.loads(html.split('<script id="opdf-data" type="application/json">')[1].split('</script>')[0])
    assert payload['blind'] and 'labels' not in payload and len(payload['ids'])==2
    return case


def test_human_import_requires_true_source_and_never_computes_performance(tmp_path):
    frames,manifest=fixture_sources(tmp_path)
    review.export_raw_case(manifest,frames,7,tmp_path/'case',roi={'bbox':[-1,5,-1,5,-1,5]},max_points=2)
    p=tmp_path/'user.json'
    data=dict(reviewer_id='SYNTHETIC_TEST_ONLY',evidence='synthetic fixture',source_message_sha256='wrong',
       point_annotations=[dict(raw_slot_id=0,label='U')])
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='hash'):review.import_human_review(tmp_path/'case/case.json',p,tmp_path/'ref_bad')
    data['source_message_sha256']='7'*64;p.write_text(json.dumps(data))
    r=review.import_human_review(tmp_path/'case/case.json',p,tmp_path/'ref')
    assert not r['independent_gt_certified'] and not r['performance_computed']


def test_d2_comparison_requires_original_b_label_trace(tmp_path):
    frames,manifest=fixture_sources(tmp_path)
    review.export_raw_case(manifest,frames,7,tmp_path/'case',roi={'bbox':[-1,5,-1,5,-1,5]},max_points=2)
    ddir=tmp_path/'d2';ddir.mkdir();a=arrays();a['labels'][0]=3
    np.savez(ddir/'seq7.npz',**a)
    (ddir/'seq7.json').write_text((frames/'seq7.json').read_text())
    with pytest.raises(ValueError,match='b__labels'):
        review.compare_case_d2(tmp_path/'case/case.json',ddir,tmp_path/'bad',max_points=2)
    a['b__labels']=arrays()['labels'];np.savez(ddir/'seq7.npz',**a)
    r=review.compare_case_d2(tmp_path/'case/case.json',ddir,tmp_path/'comparison',max_points=2)
    assert r['roi_behavior']['B_E_to_D_U']==1 and r['roi_behavior']['B_E_to_D_A']==0
    assert r['B_G_preserved_exactly'] and not r['performance_computed']


def test_d2_config_and_reason_namespace_replace_inherited_b_metadata(tmp_path):
    (tmp_path/'case.json').write_text(json.dumps({'heuristic_config_sha256':'B'}))
    (tmp_path/'review.html').write_text('<html><body>query</body></html>')
    meta={'config_sha256':'B','d2_config_sha256':'D2','method':'synthetic D2',
          'diagnostics':{'modules':{'fusion':{'reason_bits':{'B_BIT':1}}}},
          'd2_fusion_diagnostics':{'reason_bits':{'D_BIT':128},'ablation':'fusion'}}
    review.adapt_d2_review_metadata(tmp_path,meta)
    case=json.loads((tmp_path/'case.json').read_text())
    defs=json.loads((tmp_path/'reason_definitions.json').read_text())
    assert case['heuristic_config_sha256']=='D2'and case['base_B_config_sha256']=='B'
    assert defs['standard_reason_code']['reason_bits']=={'D_BIT':128}
    assert 'frozen original B' in defs['b__reason_code']['namespace']


def test_full_run_counts_raw_invalid_and_unknown_without_display_cap(tmp_path):
    frames,manifest=fixture_sources(tmp_path);ddir=tmp_path/'d2';ddir.mkdir()
    for seq in (6,7,8):
        a=arrays();a['b__labels']=a['labels'].copy();a['labels'][0]=3;a['labels'][2]=2
        np.savez(ddir/f'seq{seq}.npz',**a)
        meta=json.loads((frames/f'seq{seq}.json').read_text());meta['d2_config_sha256']='SYNTHETIC'
        (ddir/f'seq{seq}.json').write_text(json.dumps(meta))
    r=review.summarize_run_d2(manifest,frames,ddir,tmp_path/'summary')
    assert r['counts']['slots']==15 and r['counts']['finite']==12 and r['counts']['invalid']==3
    assert r['counts']['new_A']==3 and r['counts']['E_to_U']==3 and r['counts']['E_to_A']==0
    assert r['counts']['B_G_changed']==0 and not r['performance_computed']
    assert len((tmp_path/'summary/candidate_risk_exact_slots.csv').read_text().splitlines())==7
    (ddir/'seq8.npz').unlink()
    with pytest.raises(ValueError,match='Incomplete run'):
        review.summarize_run_d2(manifest,frames,ddir,tmp_path/'partial')
    assert not (tmp_path/'partial').exists()
