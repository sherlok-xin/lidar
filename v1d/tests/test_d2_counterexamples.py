"""Controlled geometric counterexamples, not real-bag semantic GT."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
DROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(DROOT))
import copy,unittest
import numpy as np,yaml
from opdf_d.multiscale import compute
from opdf_d.fusion import fuse,STANDARD_FIELDS


def config():return yaml.safe_load((DROOT/'configs/d2.yaml').read_text())


def fixture(xyz, *, label=3, intensity=3.,height=80):
    xyz=np.asarray(xyz,np.float64).reshape(-1,3);n=len(xyz)
    if n%height:raise ValueError('Synthetic fixture dimensions must align')
    valid=np.isfinite(xyz).all(1)
    a={'xyz':xyz,'valid_xyz_mask':valid,'raw_slot_id':np.arange(n,dtype=np.uint64),
       'intensity':np.full(n,intensity), 'labels':np.where(valid,label,0).astype(np.uint8),
       'score_e':np.full(n,.8,np.float32),'score_a':np.full(n,.8,np.float32),
       'available_e':valid.copy(),'available_a':valid.copy(),'reason_code':np.zeros(n,np.uint32),
       'ground__low_object_mask':np.zeros(n,bool),'ground__near_ground_mask':np.zeros(n,bool),
       'geometry__edge_protect_mask':np.zeros(n,bool),'d1__hard_structure_protect_mask':np.zeros(n,bool),
       'd1__ground_available':valid.copy(),'d1__local_height':np.full(n,1.5),
       'optical__optical_available':valid.copy(),'optical__optical_weak_score':np.zeros(n),
       'optical__local_intensity_median':np.full(n,intensity),'optical__relative_intensity_z':np.zeros(n),
       'geometry__scan_available':valid.copy(),'geometry__scan_surface_score':np.ones(n)}
    a['retain_solid_mask']=(a['labels']==1)|(a['labels']==3)
    a['retain_with_ground_mask']=a['retain_solid_mask']|(a['labels']==4)
    a['aerosol_candidate_mask']=a['labels']==2
    return a,{'metadata':{'height':height,'width':n//height,'source_bag':'SYNTHETIC_NOT_REAL','raw_message_sha256':'synthetic'}}


def volume_fixture(label=3):
    # Reproducible dense 3-D support is synthetic shape, not a material label.
    xyz=np.random.default_rng(712).uniform(-.4,.4,(960,3))+[8.,0.,1.5]
    return fixture(xyz,label=label)


class D2Counterexamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=config();cls.volume,cls.vm=volume_fixture()
        cls.vfeat=compute(cls.volume,cls.vm,cls.cfg)

    def test_dense_volume_has_real_multiscale_support_and_fusion_candidate(self):
        ms=self.vfeat['arrays']
        available=ms['d2__ms_available'].all(1)
        self.assertTrue(available.any())
        self.assertTrue(np.all(np.diff(ms['d2__ms_full_neighbor_count'],axis=1)>=0))
        self.assertTrue(np.any(ms['d2__ms_full_neighbor_count'][:,2]>96))
        self.assertLessEqual(int(ms['d2__ms_sample_count'][:,0].max()),64)
        self.assertLessEqual(int(ms['d2__ms_sample_count'][:,2].max()),96)
        self.assertTrue(np.any(ms['d2__feature_approximation_mask']))
        self.assertGreater(np.median(ms['d2__ms_effective_support_radius_m'][available,2]),
                           2*np.median(ms['d2__ms_effective_support_radius_m'][available,0]))
        geo=fuse(self.volume,self.vfeat,self.cfg,ablation='geometry_only')
        fusion=fuse(self.volume,self.vfeat,self.cfg,ablation='fusion')
        self.assertEqual(geo['diagnostics']['new_A'],0)
        self.assertGreater(fusion['diagnostics']['new_A'],0)

    def test_optical_cue_missing_volume_alone_does_not_add_A(self):
        a={k:v.copy()for k,v in self.volume.items()};a['optical__optical_available'][:]=False
        r=fuse(a,self.vfeat,self.cfg)
        self.assertEqual(r['diagnostics']['new_A'],0)

    def test_dark_plane_is_surface_not_aerosol(self):
        y,z=np.meshgrid(np.linspace(-.4,.4,20),np.linspace(1.1,1.9,20))
        a,meta=fixture(np.column_stack((np.full(y.size,8.),y.ravel(),z.ravel())))
        ms=compute(a,meta,self.cfg)
        self.assertTrue(ms['arrays']['d2__hard_plane_support'].any())
        r=fuse(a,ms,self.cfg)
        self.assertEqual(r['diagnostics']['new_A'],0)
        self.assertGreater(r['diagnostics']['new_E'],0)

    def test_thin_rod_line_axis_is_reliable_normal_is_not(self):
        a,meta=fixture(np.column_stack((np.full(240,8.),np.zeros(240),np.linspace(.8,2.,240))))
        ms=compute(a,meta,self.cfg)['arrays']
        self.assertTrue(ms['d2__hard_line_support'].any())
        self.assertFalse(ms['d2__ms_normal_available'].any())
        self.assertTrue(np.isnan(ms['d2__ms_normal']).all())
        r=fuse(a,{'arrays':ms},self.cfg)
        self.assertEqual(r['diagnostics']['new_A'],0)

    def test_dark_curved_wheel_surface_not_all_isotropic_aerosol(self):
        phi=np.linspace(0,2*np.pi,80,endpoint=False)[:,None]
        theta=np.linspace(0,2*np.pi,16,endpoint=False)[None,:]
        # Thin toroidal surface, a geometric wheel/tire counterexample only.
        x=(.35+.05*np.cos(theta))*np.cos(phi)+8.
        y=(.35+.05*np.cos(theta))*np.sin(phi)
        z=np.broadcast_to(.05*np.sin(theta)+1.,x.shape)
        a,meta=fixture(np.stack((x,y,z),axis=-1).reshape(-1,3))
        ms=compute(a,meta,self.cfg);r=fuse(a,ms,self.cfg)
        self.assertEqual(r['diagnostics']['new_A'],0)

    def test_intersecting_dark_planes_with_existing_edge_protection(self):
        y,z=np.meshgrid(np.linspace(-.4,.4,20),np.linspace(1.1,1.9,20))
        x2,y2=np.meshgrid(np.linspace(7.6,8.4,20),np.linspace(-.4,.4,20))
        xyz=np.concatenate([np.column_stack((np.full(y.size,8.),y.ravel(),z.ravel())),
                            np.column_stack((x2.ravel(),y2.ravel(),np.full(x2.size,1.5)))])
        a,meta=fixture(xyz)
        intersection=(np.abs(xyz[:,0]-8.)<.03)&(np.abs(xyz[:,2]-1.5)<.03)
        self.assertTrue(intersection.any())
        a['geometry__edge_protect_mask'][intersection]=True
        ms=compute(a,meta,self.cfg)
        r=fuse(a,ms,self.cfg)
        self.assertFalse(np.any(r['arrays']['labels'][intersection]==2))
        self.assertTrue(ms['arrays']['d2__ms_available'][intersection].any())

    def test_original_E_never_directly_becomes_A(self):
        a={k:v.copy()for k,v in self.volume.items()};a['labels'][:]=1
        r=fuse(a,self.vfeat,self.cfg)
        self.assertFalse(np.any(r['arrays']['labels']==2))
        self.assertGreater(r['diagnostics']['E_to_U'],0)

    def test_each_hard_protection_blocks_new_A_and_recalls_old_A_equally(self):
        for key in ['ground__low_object_mask','ground__near_ground_mask',
                    'geometry__edge_protect_mask','d1__hard_structure_protect_mask']:
            with self.subTest(protection=key):
                a={k:v.copy()for k,v in self.volume.items()};a[key][:]=True
                r=fuse(a,self.vfeat,self.cfg)
                self.assertEqual(r['diagnostics']['new_A'],0)
                a['labels'][:]=2
                geo=fuse(a,self.vfeat,self.cfg,ablation='geometry_only')
                fus=fuse(a,self.vfeat,self.cfg,ablation='fusion')
                self.assertTrue(np.all(geo['arrays']['labels']==3))
                np.testing.assert_array_equal(geo['arrays']['labels'],fus['arrays']['labels'])

    def test_low_stone_and_edge_clutter_flags_never_authorize_deletion(self):
        a={k:v.copy()for k,v in self.volume.items()}
        a['d1__local_height'][:]=.15;a['ground__low_object_mask'][:]=True
        a['ground__near_ground_mask'][:]=True;a['d1__low_clutter_mask']=np.ones(len(a['xyz']),bool)
        r=fuse(a,self.vfeat,self.cfg)
        self.assertEqual(r['diagnostics']['new_A'],0)

    def test_B_G_fixed_and_D1_core_is_not_material_G(self):
        a={k:v.copy()for k,v in self.volume.items()}
        a['labels'][::2]=4;a['d1__ground_core_mask']=np.ones(len(a['xyz']),bool)
        r=fuse(a,self.vfeat,self.cfg)['arrays']
        self.assertTrue(np.all(r['labels'][::2]==4))
        self.assertFalse(np.any(r['labels'][1::2]==4))

    def test_collection_budget_is_explicit_unavailable(self):
        cfg=copy.deepcopy(self.cfg);cfg['d2']['max_collect_neighbors']=7
        result=compute(self.volume,self.vm,cfg)
        self.assertTrue(result['arrays']['d2__ms_oversaturated'].any())
        self.assertFalse(result['arrays']['d2__ms_available'].any())
        r=fuse(self.volume,result,cfg)
        self.assertEqual(r['diagnostics']['new_A'],0)

    def test_empty_NaN_duplicates_unavailable_no_fabricated_points(self):
        for xyz in [np.empty((0,3)),np.full((80,3),np.nan),np.broadcast_to([8.,0.,1.5],(80,3)).copy()]:
            with self.subTest(n=len(xyz),finite=int(np.isfinite(xyz).sum())):
                a,meta=fixture(xyz);ms=compute(a,meta,self.cfg)
                self.assertFalse(ms['arrays']['d2__ms_available'].any())
                r=fuse(a,ms,self.cfg)['arrays']
                self.assertEqual(r['labels'].shape,(len(xyz),))
                self.assertFalse(np.any(r['labels']==2))
                np.testing.assert_array_equal(r['b__labels'],a['labels'])

    def test_deterministic_features_and_original_arrays_not_modified(self):
        before={k:v.copy()for k,v in self.volume.items()}
        result=compute(self.volume,self.vm,self.cfg)
        for k,v in self.vfeat['arrays'].items():
            np.testing.assert_allclose(v,result['arrays'][k],rtol=0,atol=0,equal_nan=True)
        fuse(self.volume,result,self.cfg)
        for k,v in before.items():np.testing.assert_array_equal(self.volume[k],v)


if __name__=='__main__':unittest.main(verbosity=2)
