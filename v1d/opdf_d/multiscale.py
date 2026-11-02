"""D2 true radius neighborhoods, deterministic radial/octant sampling, no GT."""
from __future__ import annotations
import time
import numpy as np
from scipy.spatial import cKDTree

VERSION='OPDF-V1-D2-ms/0.1.0'
REASONS={'INVALID':1,'B_G_SKIPPED':2,'INSUFFICIENT_SUPPORT':4,'OVER_COLLECTION_BUDGET':8,
         'DUPLICATE_OR_DEGENERATE':16,'INADEQUATE_RADIAL_COVERAGE':32,
         'STABLE_PLANE':64,'STABLE_LINE':128,'MULTISCALE_VOLUME':256,'STRUCTURE_VOLUME_CONFLICT':512}


def _sample(neighbor_indices, points, query, radius, cap, raw_ids, shell_boundary):
    """Choose a representative from every occupied octant/shell, then distribute
    remaining slots over canonical original IDs. This is not nearest-k sampling.
    """
    nb=np.asarray(neighbor_indices,np.int64)
    if len(nb)<=cap:return nb
    delta=points[nb]-query
    dist=np.linalg.norm(delta,axis=1)
    octant=(delta[:,0]>=0).astype(np.int16)+2*(delta[:,1]>=0)+4*(delta[:,2]>=0)
    group=octant+8*(dist>=shell_boundary*radius)
    # In every occupied stratum preserve its farthest support to avoid using the
    # same tiny nearest-k ball at all requested scales. Break ties by raw ID.
    order=np.lexsort((raw_ids[nb],dist,group))
    end=np.r_[np.flatnonzero(np.diff(group[order]))+1,len(order)]-1
    anchors=order[end]
    canon=np.argsort(raw_ids[nb],kind='stable')
    keep=np.zeros(len(nb),bool);keep[anchors]=True
    remaining=canon[~keep[canon]]
    take=max(0,cap-len(anchors))
    if take:keep[remaining[np.linspace(0,len(remaining)-1,take,dtype=np.int64)]]=True
    return nb[np.flatnonzero(keep)[:cap]]


def compute(arrays, metadata, config):
    """Input D1 complete saved arrays/meta; output new d2__ arrays only."""
    cfg=config['d2'];start=time.perf_counter()
    if cfg['min_consistent_structure_scales']!=2:
        raise ValueError('This version freezes two reliable structure scales')
    xyz=np.asarray(arrays['xyz'],np.float64);n=len(xyz)
    valid=np.asarray(arrays['valid_xyz_mask'],bool)&np.isfinite(xyz).all(1)
    raw=np.asarray(arrays['raw_slot_id'],np.uint64)
    labels=np.asarray(arrays['labels'])
    query_mask=valid&(labels!=4)  # B-G is deliberately fixed; support still all finite.
    vi=np.flatnonzero(valid);qi=np.flatnonzero(query_mask)
    out={}
    numeric=['radius_m','effective_support_radius_m','sampling_fraction','linearity','planarity',
             'isotropy','scattering','plane_rms_m','line_rms_m','normal_gap','axis_gap']
    for key in numeric:out['d2__ms_'+key]=np.full((n,3),np.nan,np.float32)
    for key in ['full_neighbor_count','sample_count','unique_support_count','octant_occupancy','radial_shell_coverage','phase_support']:
        out['d2__ms_'+key]=np.zeros((n,3),np.int32)
    for key in ['available','oversaturated','degenerate','normal_available','line_axis_available','plane_support','line_support','volume_support']:
        out['d2__ms_'+key]=np.zeros((n,3),bool)
    out['d2__ms_eigenvalues']=np.full((n,3,3),np.nan,np.float32)
    out['d2__ms_normal']=np.full((n,3,3),np.nan,np.float32)
    out['d2__ms_line_axis']=np.full((n,3,3),np.nan,np.float32)
    out['d2__feature_approximation_mask']=np.zeros(n,bool)
    reason=np.zeros(n,np.uint32);reason[~valid]|=REASONS['INVALID'];reason[valid&~query_mask]|=REASONS['B_G_SKIPPED']
    stage={'tree_build_ms':0.,'ball_counts_ms':0.,'ball_collection_sampling_ms':0.,'pca_features_ms':0.,'cross_scale_ms':0.}
    if not len(vi):
        stage['total_multiscale_ms']=(time.perf_counter()-start)*1000
        return _finish(out,reason,cfg,stage,n,0,0)
    points=xyz[vi];raw_valid=raw[vi]
    t=time.perf_counter();tree=cKDTree(points);stage['tree_build_ms']=(time.perf_counter()-t)*1000
    ranges=np.linalg.norm(xyz[qi],axis=1)
    # Exact point counts at each radius, not capped fitting counts.
    for s in range(3):
        radii=np.clip(ranges*cfg['range_factors'][s],cfg['radius_min_m'][s],cfg['radius_max_m'][s])
        out['d2__ms_radius_m'][qi,s]=radii
        t=time.perf_counter()
        count=tree.query_ball_point(xyz[qi],radii,return_length=True,workers=int(cfg['workers']))-1
        stage['ball_counts_ms']+=(time.perf_counter()-t)*1000
        out['d2__ms_full_neighbor_count'][qi,s]=count
        oversized=count>cfg['max_collect_neighbors']
        out['d2__ms_oversaturated'][qi[oversized],s]=True
        reason[qi[oversized]]|=REASONS['OVER_COLLECTION_BUDGET']
        eligible=(count>=cfg['min_samples'][s])&~oversized
        reason[qi[~eligible&~oversized]]|=REASONS['INSUFFICIENT_SUPPORT']
        selected=np.flatnonzero(eligible)
        cap=int(cfg['sample_caps'][s]);batch=int(cfg['batch_size'])
        for begin in range(0,len(selected),batch):
            pos=selected[begin:begin+batch];ids=qi[pos];q=xyz[ids];rr=radii[pos]
            t=time.perf_counter()
            balls=tree.query_ball_point(q,rr,return_sorted=True,workers=int(cfg['workers']))
            samples=np.zeros((len(ids),cap,3),np.float64)
            weights=np.zeros((len(ids),cap),bool)
            max_radius=np.zeros(len(ids));octants=np.zeros(len(ids),np.int32)
            shells=np.zeros(len(ids),np.int32);phases=np.zeros(len(ids),np.int32)
            height=int(metadata.get('metadata',metadata).get('height',80))
            for row,nb in enumerate(balls):
                nb=np.asarray(nb,np.int64)
                delta=points[nb]-q[row]
                distance=np.linalg.norm(delta,axis=1)
                nb=nb[distance>cfg['distinct_xyz_quantum_m']]  # exclude self and coincident support
                out['d2__feature_approximation_mask'][ids[row]]|=len(nb)>cap
                chosen=_sample(nb,points,q[row],rr[row],cap,raw_valid,cfg['radial_shell_boundary_fraction'])
                if not len(chosen):continue
                coords=points[chosen]
                # Unique fitting support only; full count above remains raw observation count.
                _,unique=np.unique(np.rint(coords/cfg['distinct_xyz_quantum_m']).astype(np.int64),axis=0,return_index=True)
                chosen=chosen[np.sort(unique)]
                delta=points[chosen]-q[row]
                distance=np.linalg.norm(delta,axis=1)
                m=len(chosen);samples[row,:m]=delta;weights[row,:m]=True
                out['d2__ms_sample_count'][ids[row],s]=m
                out['d2__ms_unique_support_count'][ids[row],s]=m
                out['d2__ms_sampling_fraction'][ids[row],s]=m/max(1,len(nb))
                max_radius[row]=float(distance.max()) if m else 0.
                bucket=(delta[:,0]>=0).astype(np.int16)+2*(delta[:,1]>=0)+4*(delta[:,2]>=0)
                octants[row]=len(np.unique(bucket))
                shells[row]=len(np.unique(distance>=cfg['radial_shell_boundary_fraction']*rr[row]))
                phases[row]=len(np.unique(raw_valid[chosen]%max(1,height)))
            stage['ball_collection_sampling_ms']+=(time.perf_counter()-t)*1000
            t=time.perf_counter()
            number=weights.sum(1);ww=weights.astype(np.float64)
            mean=np.einsum('bk,bki->bi',ww,samples)/np.maximum(number,1)[:,None]
            centered=samples-mean[:,None,:]
            covariance=np.einsum('bk,bki,bkj->bij',ww,centered,centered)/np.maximum(number,1)[:,None,None]
            eig,vec=np.linalg.eigh(covariance);eig=np.maximum(eig,0)
            extent=eig[:,2]>cfg['min_eigen_extent_m2']
            coverage=max_radius>=cfg['min_effective_radius_fraction']*rr
            available=(number>=cfg['min_samples'][s])&extent&coverage
            degenerate=(number<cfg['min_samples'][s])|~extent
            out['d2__ms_degenerate'][ids,s]=degenerate
            reason[ids[degenerate]]|=REASONS['DUPLICATE_OR_DEGENERATE']
            reason[ids[~coverage]]|=REASONS['INADEQUATE_RADIAL_COVERAGE']
            out['d2__ms_effective_support_radius_m'][ids,s]=max_radius
            out['d2__ms_octant_occupancy'][ids,s]=octants
            out['d2__ms_radial_shell_coverage'][ids,s]=shells
            out['d2__ms_phase_support'][ids,s]=phases
            aa=ids[available];ev=eig[available];rv=rr[available]
            denom=np.maximum(ev[:,2],1e-20)
            linear=(ev[:,2]-ev[:,1])/denom;planar=(ev[:,1]-ev[:,0])/denom
            iso=ev[:,0]/denom;scatter=3*ev[:,0]/np.maximum(ev.sum(1),1e-20)
            plane_rms=np.sqrt(ev[:,0]);line_rms=np.sqrt(ev[:,0]+ev[:,1])
            for key,value in [('linearity',linear),('planarity',planar),('isotropy',iso),('scattering',scatter),
                              ('plane_rms_m',plane_rms),('line_rms_m',line_rms),('normal_gap',planar),('axis_gap',linear)]:
                out['d2__ms_'+key][aa,s]=value
            out['d2__ms_available'][aa,s]=True
            out['d2__ms_eigenvalues'][aa,s]=ev
            normal_ok=planar>=cfg['normal_planarity_min'];axis_ok=linear>=cfg['line_axis_linearity_min']
            out['d2__ms_normal_available'][aa,s]=normal_ok;out['d2__ms_line_axis_available'][aa,s]=axis_ok
            out['d2__ms_normal'][aa[normal_ok],s]=vec[available][normal_ok,:,0]
            out['d2__ms_line_axis'][aa[axis_ok],s]=vec[available][axis_ok,:,2]
            plane=(planar>=cfg['hard_planarity_min'])&(plane_rms/rv<=cfg['hard_plane_rms_radius_max'])
            line=(linear>=cfg['hard_linearity_min'])&(line_rms/rv<=cfg['hard_line_rms_radius_max'])
            volume=(iso>=cfg['volume_isotropy_min'])&(scatter>=cfg['volume_scattering_min'])&\
             (octants[available]>=cfg['volume_octants_min'])&(shells[available]>=cfg['volume_shells_min'])&\
             (phases[available]>=cfg['volume_phases_min'])
            out['d2__ms_plane_support'][aa,s]=plane;out['d2__ms_line_support'][aa,s]=line
            out['d2__ms_volume_support'][aa,s]=volume
            stage['pca_features_ms']+=(time.perf_counter()-t)*1000
    return _finish(out,reason,cfg,stage,n,len(qi),len(vi),start)


def _finish(out,reason,cfg,timing,n,queried,finite,start=None):
    t=time.perf_counter()
    for kind,key in [('normal','plane'),('line_axis','line')]:
        vectors=out['d2__ms_'+kind];available=out['d2__ms_'+kind+'_available']
        support=out['d2__ms_'+key+'_support'];consistency=np.full(n,np.nan,np.float32)
        consistent=np.zeros(n,bool)
        for a,b in [(0,1),(0,2),(1,2)]:
            mask=available[:,a]&available[:,b]
            dot=np.abs(np.einsum('ij,ij->i',vectors[:,a],vectors[:,b]))
            previous=consistency.copy()
            consistency[mask]=np.fmax(previous[mask],dot[mask])
            consistent|=mask&support[:,a]&support[:,b]&(dot>=cfg['structure_consistency_cos_min'])
        out['d2__'+kind+'_consistency']=consistency
        out['d2__hard_'+key+'_support']=consistent
    any_structure=np.any(out['d2__ms_plane_support']|out['d2__ms_line_support'],axis=1)
    volume=out['d2__ms_volume_support'].sum(1)>=cfg['min_volume_scales']
    if cfg['volume_requires_large']:volume&=out['d2__ms_volume_support'][:,2]
    out['d2__hard_structure_any_scale']=any_structure
    out['d2__volume_candidate']=volume
    out['d2__geometry_conflict']=volume&any_structure
    reason[out['d2__hard_plane_support']]|=REASONS['STABLE_PLANE']
    reason[out['d2__hard_line_support']]|=REASONS['STABLE_LINE']
    reason[volume]|=REASONS['MULTISCALE_VOLUME']
    reason[out['d2__geometry_conflict']]|=REASONS['STRUCTURE_VOLUME_CONFLICT']
    out['d2__ms_reason_code']=reason
    timing['cross_scale_ms']=(time.perf_counter()-t)*1000
    if start is not None:timing['total_multiscale_ms']=(time.perf_counter()-start)*1000
    return {'arrays':out,'diagnostics':{'version':VERSION,'status':'OK'if finite else'UNAVAILABLE',
     'reason_bits':REASONS,'finite':finite,'queried_non_B_G':queried,
     'support_domain':'all finite raw coordinates; B-G queries skipped, outputs unavailable there',
     'sampling':'radius exact count; deterministic occupied octant/radial-shell anchors plus raw-ID spread',
     'full_count_is_observations':'may include duplicate XYZ; unique_support_count is fitting-sample unique count only',
     'approximation':'PCA computed from capped spatial/radial sample, no query/identity nearest-neighbor propagation',
     'sample_caps':cfg['sample_caps'],'max_collect_neighbors':cfg['max_collect_neighbors'],
     'available_per_scale':out['d2__ms_available'].sum(0).tolist(),
     'oversaturated_per_scale':out['d2__ms_oversaturated'].sum(0).tolist(),
     'plane_support_per_scale':out['d2__ms_plane_support'].sum(0).tolist(),
     'line_support_per_scale':out['d2__ms_line_support'].sum(0).tolist(),
     'volume_support_per_scale':out['d2__ms_volume_support'].sum(0).tolist(),
     'volume_candidate':int(volume.sum()),'geometry_conflict':int(out['d2__geometry_conflict'].sum()),
     'timings_ms':timing,'semantic_truth':'UNKNOWN'}}
