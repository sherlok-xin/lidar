"""D3 registration probes only. NN correspondence is never particle identity/velocity."""
import numpy as np
from scipy.spatial import cKDTree

def voxel_indices(xyz,mask,voxel=.25,limit=2500):
    ids=np.flatnonzero(np.asarray(mask,bool)&np.isfinite(xyz).all(1))
    if not len(ids):return ids
    _,first=np.unique(np.floor(xyz[ids]/voxel).astype(np.int64),axis=0,return_index=True)
    selected=ids[np.sort(first)]
    if len(selected)>limit:selected=selected[np.linspace(0,len(selected)-1,limit,dtype=int)]
    return selected # original indices, not voxel centroids or invented echoes

def observability(points,normals):
    good=np.isfinite(points).all(1)&np.isfinite(normals).all(1)
    p=points[good];n=normals[good]
    if len(p)<30:return {'available':False,'reason':'INSUFFICIENT_NORMAL_SUPPORT','normal_points':len(p),'rank':0}
    n=n/np.maximum(np.linalg.norm(n,axis=1)[:,None],1e-12)
    p=p-np.median(p,axis=0);scale=max(float(np.median(np.linalg.norm(p,axis=1))),1.)
    J=np.column_stack([np.cross(p/scale,n),n]);eig=np.maximum(np.linalg.eigvalsh(J.T@J/len(J)),0)
    ratio=eig/max(eig.max(),1e-12);rank=int((ratio>1e-3).sum())
    return {'available':rank==6,'reason':'GEOMETRIC_NORMAL_PROBE_ONLY'if rank==6 else'UNOBSERVABLE_DIRECTIONS',
            'normal_points':len(p),'rank':rank,'eigenvalues':eig.tolist(),'relative_eigenvalues':ratio.tolist(),
            'rotational_scale_m':scale,'certifies_static_background':False}

def rigid_icp(source,target,initial=None,max_iterations=12,gate=.6,trim=.75):
    if len(source)<40 or len(target)<40:return {'available':False,'reason':'INSUFFICIENT_SUPPORT'}
    T=np.eye(4)if initial is None else np.asarray(initial,float).copy();tree=cKDTree(target)
    for it in range(max_iterations):
        transformed=source@T[:3,:3].T+T[:3,3]
        distance,idx=tree.query(transformed,k=1,workers=2);use=np.isfinite(distance)&(distance<gate)
        if use.sum()<40:return {'available':False,'reason':'INSUFFICIENT_GATED_OVERLAP'}
        threshold=np.quantile(distance[use],trim);use&=distance<=threshold
        a=transformed[use];b=target[idx[use]];ac=a.mean(0);bc=b.mean(0)
        u,_,vt=np.linalg.svd((a-ac).T@(b-bc));R=vt.T@u.T
        if np.linalg.det(R)<0:vt[-1]*=-1;R=vt.T@u.T
        step=np.eye(4);step[:3,:3]=R;step[:3,3]=bc-R@ac;T=step@T
        if np.linalg.norm(step[:3,3])<1e-5 and np.linalg.norm(R-np.eye(3))<1e-5:break
    transformed=source@T[:3,:3].T+T[:3,3];distance,_=tree.query(transformed,k=1,workers=2)
    matched=distance<gate
    return {'available':True,'T_target_from_source':T.tolist(),'iterations':it+1,
            'translation_norm_m':float(np.linalg.norm(T[:3,3])),
            'yaw_deg':float(np.degrees(np.arctan2(T[1,0],T[0,0]))),
            'gate_overlap_fraction':float(matched.mean()),'nn_median_m':float(np.median(distance)),
            'nn_p90_m':float(np.quantile(distance,.9)),'correspondence_semantics':'geometric nearest neighbor, not physical identity',
            'independent_ego_pose':False}

def overlap_probe(source,target,T=None,gate=.15):
    if len(source)<3 or len(target)<3:return {'available':False,'reason':'INSUFFICIENT_ROI_POINTS'}
    moved=source if T is None else source@T[:3,:3].T+T[:3,3]
    d,_=cKDTree(target).query(moved,k=1,workers=2)
    reverse,_=cKDTree(moved).query(target,k=1,workers=2)
    return {'available':True,'source_points':len(source),'target_points':len(target),
            'forward_within_gate':float((d<gate).mean()),'reverse_within_gate':float((reverse<gate).mean()),
            'nn_median_m':float(np.median(d)),'distance_gate_m':gate,
            'meaning':'ROI geometric overlap only; changing masks/occlusion/density/scan phase may explain it',
            'instance_identity_established':False,'particle_velocity_inferred':False}
