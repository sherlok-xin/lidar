from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from opdf_d.temporal_probe import observability,rigid_icp,voxel_indices,overlap_probe

def test_flat_road_has_unobservable_degrees_not_full_ego_pose():
    x,y=np.meshgrid(np.linspace(-10,10,25),np.linspace(-5,5,20));p=np.column_stack([x.ravel(),y.ravel(),np.zeros(x.size)])
    r=observability(p,np.tile([0.,0.,1.],(len(p),1)))
    assert r['rank']==3 and not r['available'] and not r['certifies_static_background']

def test_rigid_synthetic_registration_does_not_infer_particle_velocity():
    rng=np.random.default_rng(7);a=rng.uniform(-2,2,(1500,3));shift=np.array([.05,-.03,.02]);b=a+shift
    r=rigid_icp(a,b);assert r['available'] and np.linalg.norm(np.asarray(r['T_target_from_source'])[:3,3]-shift)<.005
    o=overlap_probe(a,b,np.asarray(r['T_target_from_source']))
    assert not o['particle_velocity_inferred']and not o['instance_identity_established']

def test_sparse_failure_is_not_static_proof_and_voxel_selection_is_exact():
    a=np.array([[0.,0.,0.],[.01,0,0],[1.,1,1],[np.nan,0,0]])
    ids=voxel_indices(a,np.ones(4,bool),.25)
    assert ids.tolist()==[0,2]and not rigid_icp(a[:2],a[:2])['available']
