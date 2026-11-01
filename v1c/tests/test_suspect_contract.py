"""Review masks must never alter source labels or treat weak intensity as deletion."""
from pathlib import Path
import sys
import numpy as np
sys.dont_write_bytecode=True
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
from opdf_c.suspect import compute
from test_gates_contract import evidence

def test_additive_masks_leave_every_source_field_unchanged():
    a,cfg=evidence();before={k:v.copy() for k,v in a.items()};x=compute(a,cfg,{'uniform_low_enabled':True})
    assert 'labels' not in x and 'retain_solid_mask' not in x
    assert all(np.array_equal(a[k],v,equal_nan=True) for k,v in before.items())
    assert not x['aerosol_suspect_mask'][0] # already A: not a new suspect deletion
    assert not x['aerosol_suspect_mask'][6] # invalid

def test_uniform_low_is_only_one_category_not_sufficient_by_itself():
    a,cfg=evidence();a['intensity'][:]=1;a['optical__local_intensity_median'][:]=1;a['optical__relative_intensity_z'][:]=0
    a['optical__optical_weak_score'][:]=0;a['geometry__scan_discontinuity_score'][:]=0;a['geometry__spatial_diffuse_score'][:]=0
    assert not compute(a,cfg,{'uniform_low_enabled':True})['aerosol_suspect_mask'].any()

def test_single_uniform_channel_ablation_preserves_protected_unknown():
    a,cfg=evidence();a['labels'][1]=3;a['intensity'][1]=1;a['optical__local_intensity_median'][1]=1
    a['optical__relative_intensity_z'][1]=0;a['optical__optical_weak_score'][1]=0;a['geometry__spatial_diffuse_score'][1]=0
    b=compute(a,cfg,{'uniform_low_enabled':False});c=compute(a,cfg,{'uniform_low_enabled':True})
    assert not b['aerosol_suspect_mask'][1] and c['aerosol_suspect_mask'][1]
    assert c['suspect_protected_mask'][1] and a['labels'][1]==3

def test_missing_geometry_cannot_promote_single_optical_probe():
    a,cfg=evidence();a['geometry__scan_available'][:]=False;a['geometry__spatial_available'][:]=False
    c=compute(a,cfg,{'uniform_low_enabled':True})
    assert not c['aerosol_suspect_mask'].any() and not c['aerosol_suspect_available_mask'].any()
