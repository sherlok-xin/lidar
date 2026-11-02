"""Software counterexamples only; synthetic shapes are not measured material GT."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
import numpy as np
from opdf_d.ground_clutter import compute,ablate_upper

def fixture(objects=None,reliable=True,strong=False,available=True):
 x,y=np.meshgrid(np.arange(-3,3.01,.1),np.arange(-3,3.01,.1));g=np.c_[x.ravel(),y.ravel(),np.zeros(x.size)];obj=np.asarray(objects if objects is not None else [],float).reshape(-1,3);xyz=np.r_[g,obj].astype(np.float32);n=len(xyz);valid=np.isfinite(xyz).all(1);labels=np.where(valid,np.where(xyz[:,2]<=.035,4,3),0).astype(np.uint8)
 a={'xyz':xyz,'intensity':np.ones(n,np.float32),'valid_xyz_mask':valid,'raw_slot_id':np.arange(n,dtype=np.uint64),'labels':labels,'ground__ground_available':valid.copy(),'ground__height_above_ground':xyz[:,2].copy(),'geometry__scan_available':np.full(n,available,bool),'geometry__spatial_available':np.full(n,available,bool),'geometry__scan_surface_score':np.full(n,.1,np.float32),'geometry__spatial_surface_score':np.full(n,.1,np.float32)}
 if strong:a['geometry__scan_surface_score'][len(g):]=.95;a['geometry__spatial_surface_score'][len(g):]=.95
 m={'diagnostics':{'modules':{'ground':{'reliable':reliable,'plane_z_ax_by_c':[0,0,0]}}}}
 return a,m,np.arange(len(g),n)

def block(zs=(.06,.10,.14),span=.25):
 x,y,z=np.meshgrid(np.linspace(-span,span,6),np.linspace(-span,span,6),zs);return np.c_[x.ravel(),y.ravel(),z.ravel()]

class GroundClutterTests(unittest.TestCase):
 def test_low_stone_compact_kept_for_all_upper_ablations(self):
  a,m,ids=fixture(block());r=compute(a,m,{})
  self.assertTrue(r['arrays']['d1__hard_structure_protect_mask'][ids].all())
  for h in [.035,.07,.10,.15]:self.assertTrue(ablate_upper(r['arrays'],upper_m=h)['nonground_display_mask'][ids].all())
 def test_sparse_one_two_three_point_low_bumps_are_unknown_protected(self):
  for count in [1,2,3]:
   objects=np.c_[np.arange(count)*.03,np.zeros(count),np.full(count,.05)]
   a,m,ids=fixture(objects,available=True);r=compute(a,m,{})
   self.assertTrue(r['arrays']['d1__hard_structure_protect_mask'][ids].all())
   self.assertTrue(r['arrays']['d1__risk_unknown_mask'][ids].all())
   for upper in [.035,.07,.10,.15]:self.assertTrue(ablate_upper(r['arrays'],upper_m=upper)['nonground_display_mask'][ids].all())
 def test_direct_hard_point_not_diluted_in_mixed_cluster(self):
  x,y=np.meshgrid(np.arange(-1.3,1.31,.08),np.arange(-.3,.31,.08));objects=np.c_[x.ravel(),y.ravel(),np.full(x.size,.075)]
  a,m,ids=fixture(objects);a['geometry__scan_surface_score'][ids[0]]=.95;a['geometry__spatial_surface_score'][ids[0]]=.95
  r=compute(a,m,{})
  self.assertTrue(r['arrays']['d1__hard_structure_protect_mask'][ids[0]])
  self.assertTrue(r['arrays']['d1__nonground_display_mask'][ids[0]])
  self.assertFalse(r['arrays']['d1__low_clutter_mask'][ids[0]])
 def test_thin_vertical_pole_and_wheel_kept(self):
  z=np.linspace(.04,.54,50);pole=np.c_[np.zeros(50)+1,np.zeros(50),z];theta=np.linspace(0,2*np.pi,100);wheel=np.c_[np.cos(theta)*.25-1,np.zeros(100),np.sin(theta)*.22+.28]
  a,m,ids=fixture(np.r_[pole,wheel]);r=compute(a,m,{})
  self.assertTrue(r['arrays']['d1__hard_structure_protect_mask'][ids].all());self.assertTrue(r['arrays']['d1__nonground_display_mask'][ids].all())
 def test_dark_flat_hard_surface_protected_without_intensity_rule(self):
  x,y=np.meshgrid(np.linspace(-1.3,1.3,35),np.linspace(-.3,.3,10));o=np.c_[x.ravel(),y.ravel(),np.full(x.size,.06)]
  a,m,ids=fixture(o,strong=True);a['intensity'][ids]=0;r=compute(a,m,{})
  self.assertTrue(r['arrays']['d1__hard_structure_protect_mask'][ids].all());self.assertTrue(r['arrays']['d1__nonground_display_mask'][ids].all())
  a['intensity'][ids]=100;rr=compute(a,m,{})
  np.testing.assert_array_equal(r['arrays']['d1__nonground_display_mask'],rr['arrays']['d1__nonground_display_mask'])
 def test_unreliable_ground_never_removes_finite_points(self):
  a,m,ids=fixture(block(),reliable=False);r=compute(a,m,{})
  self.assertEqual(r['diagnostics']['status'],'ABSTAIN');self.assertFalse(r['arrays']['d1__ground_core_mask'].any());self.assertFalse(r['arrays']['d1__low_clutter_mask'].any());np.testing.assert_array_equal(r['arrays']['d1__nonground_display_mask'],a['valid_xyz_mask'])
 def test_geometry_unavailable_unknown_retained(self):
  a,m,ids=fixture(block(zs=(.06,),span=1.4),available=False);r=compute(a,m,{})
  self.assertFalse(r['arrays']['d1__low_clutter_mask'][ids].any());self.assertTrue(r['arrays']['d1__nonground_display_mask'][ids].all());self.assertTrue(r['arrays']['d1__risk_unknown_mask'][ids].all())
 def test_thin_connected_diffuse_sheet_is_only_display_candidate(self):
  x,y=np.meshgrid(np.arange(-1.3,1.31,.08),np.arange(-.3,.31,.08));o=np.c_[x.ravel(),y.ravel(),np.full(x.size,.075)]
  a,m,ids=fixture(o);r=compute(a,m,{})
  self.assertTrue(r['arrays']['d1__low_clutter_mask'][ids].all());self.assertTrue(r['arrays']['d1__risk_unknown_mask'][ids].all());np.testing.assert_array_equal(r['arrays']['labels'],a['labels']);self.assertFalse(r['arrays']['d1__ground_core_mask'][ids].any())
 def test_full_ball_counts_are_not_cap15(self):
  a,m,ids=fixture(block(zs=(.075,),span=1.4));r=compute(a,m,{})
  self.assertGreater(r['arrays']['d1__large_ball_count'].max(),15);self.assertTrue(np.all(r['arrays']['d1__large_ball_count']>=r['arrays']['d1__small_ball_count']))
 def test_mask_partition_original_fields_and_nan_slots(self):
  a,m,ids=fixture(np.r_[block(),[[np.nan,0,0]]]);original={k:v.copy()for k,v in a.items()};r=compute(a,m,{})
  for k,v in original.items():np.testing.assert_array_equal(r['arrays'][k],v)
  z=r['arrays'];np.testing.assert_array_equal(z['d1__nonground_strict_mask'],a['valid_xyz_mask']&~z['d1__ground_core_mask']);np.testing.assert_array_equal(z['d1__nonground_display_mask'],z['d1__nonground_strict_mask']&~z['d1__low_clutter_mask']);self.assertFalse((z['d1__ground_core_mask']&z['d1__low_clutter_mask']).any());self.assertFalse(z['d1__nonground_display_mask'][-1])
 def test_single_variable_upper_masks_equal_fresh_compute(self):
  a,m,_=fixture(block());base=compute(a,m,{})
  for upper in [.035,.07,.10,.15]:
   fresh=compute(a,m,{'d1':{'ground_upper_m':upper}});ab=ablate_upper(base['arrays'],upper_m=upper)
   for name,mask in ab.items():np.testing.assert_array_equal(mask,fresh['arrays']['d1__'+name])
 def test_local_correction_is_real_and_unavailable_support_falls_back(self):
  a,m,_=fixture();a['xyz'][:,2]=.02*np.sin(a['xyz'][:,0]);a['ground__height_above_ground']=a['xyz'][:,2].copy();r=compute(a,m,{})
  self.assertTrue(r['arrays']['d1__local_model_used'].any());self.assertGreater(np.nanmax(np.abs(r['arrays']['d1__local_ground_correction'])),.001)

if __name__=='__main__':unittest.main()
