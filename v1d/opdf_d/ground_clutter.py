"""D1 local anchored-ground and conservative near-ground display diagnostics.

Material identity remains unknown. No source label, occupancy or original slot is
changed. Full ball counts at two physical radii do not reuse a capped kNN list.
"""
from __future__ import annotations
import time
import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

REASON_BITS = {
 'INVALID_XYZ':1, 'GROUND_UNAVAILABLE':2, 'LOCAL_MODEL_USED':4,
 'GLOBAL_ANCHOR_FALLBACK':8, 'GROUND_CORE_CANDIDATE':16,
 'COMPACT_STRUCTURE_PROTECT':32, 'VERTICAL_STRUCTURE_PROTECT':64,
 'SURFACE_STRUCTURE_PROTECT':128, 'GROUND_CONNECTED':256,
 'THIN_CLUSTER':512, 'FULL_BALL_MULTISCALE_SUPPORT':1024,
 'LOW_CLUTTER_DISPLAY_CANDIDATE':2048, 'MATERIAL_RISK_UNKNOWN':4096,
 'GEOMETRY_UNAVAILABLE_RETAIN':8192, 'SPARSE_COMPONENT_PROTECT':16384,
}
DEFAULTS = dict(ground_lower_m=-.10, ground_upper_m=.07,
 local_cell_m=1.,seed_lower_m=-.10,seed_upper_m=.035,seed_quantile=.35,
 min_seed_points_per_cell=3,local_radius_m=2.5,min_local_seed_cells=5,
 min_xy_span_m=1.,min_local_quadrants=3,local_inlier_residual_m=.05,
 max_local_fit_mad_m=.025,max_local_slope=.08,max_local_correction_m=.08,
 cluster_min_height_m=.035,cluster_max_height_m=.55,
 cluster_xy_voxel_m=.30,cluster_z_voxel_m=.08,cluster_min_points=8,
 compact_max_span_m=1.2,compact_min_height_m=.04,hard_min_points=4,
 hard_vertical_span_m=.18,hard_high_quantile_m=.40,
 hard_scan_surface_min=.80,hard_spatial_surface_min=.80,hard_surface_fraction_min=.25,
 clutter_min_lateral_span_m=1.2,clutter_max_vertical_span_m=.06,
 contact_ground_band_m=.03,contact_radius_m=.25,contact_fraction_min=.35,
 clutter_base_height_max_m=.08,small_radius_m=.15,large_radius_m=.35,
 min_small_ball_count=3,min_large_ball_count=8,
 multiscale_support_fraction_min=.70,min_geometry_available_fraction=.70,workers=2)


def _ground_diagnostics(metadata):
    if isinstance(metadata.get('diagnostics'),dict):
        return metadata['diagnostics'].get('modules',{}).get('ground',{})
    return metadata.get('ground_diagnostics',{})


def _threshold_masks(new,valid,lower,upper):
    h=new['d1__local_height'];av=new['d1__ground_available']
    protect=new['d1__hard_structure_protect_mask']
    core=valid&av&np.isfinite(h)&(h>=lower)&(h<=upper)&~protect&~new['d1__low_clutter_eligible_mask']
    clutter=new['d1__low_clutter_eligible_mask']&~core&~protect
    return core,clutter,valid&~core,valid&~core&~clutter


def ablate_upper(result_arrays, *, lower_m=-.10, upper_m=.07):
    """Actual single-variable mask counterfactual using unchanged local evidence."""
    valid=np.asarray(result_arrays['valid_xyz_mask'],bool)&np.isfinite(result_arrays['xyz']).all(1)
    return dict(zip(('ground_core_mask','low_clutter_mask','nonground_strict_mask','nonground_display_mask'),
                    _threshold_masks(result_arrays,valid,lower_m,upper_m)))


def compute(arrays,metadata,config):
    cfg={**DEFAULTS,**config.get('d1',{})};started=time.perf_counter()
    xyz=np.asarray(arrays['xyz'],np.float64);n=len(xyz)
    valid=np.asarray(arrays['valid_xyz_mask'],bool)&np.isfinite(xyz).all(1)
    if xyz.shape!=(n,3):raise ValueError('xyz must be Nx3')
    for k,v in arrays.items():
        if np.asarray(v).ndim==0 or len(v)!=n:raise ValueError('original array not slot aligned: '+k)
    new={k:np.full(n,np.nan,np.float32)for k in (
     'd1__local_height','d1__ground_z','d1__global_anchor_height','d1__local_ground_correction',
     'd1__local_fit_mad','d1__cluster_lateral_span','d1__cluster_vertical_span',
     'd1__cluster_ground_contact_fraction','d1__cluster_multiscale_support_fraction',
     'd1__cluster_geometry_available_fraction','d1__cluster_hard_surface_fraction',
     'd1__ground_core_score','d1__low_clutter_score')}
    new.update({k:np.zeros(n,bool)for k in ('d1__ground_available','d1__local_model_used',
     'd1__hard_structure_protect_mask','d1__low_clutter_eligible_mask')})
    new['d1__local_seed_support_count']=np.zeros(n,np.int16)
    new['d1__small_ball_count']=np.zeros(n,np.int32);new['d1__large_ball_count']=np.zeros(n,np.int32)
    new['d1__cluster_id']=np.full(n,-1,np.int32);new['d1__cluster_point_count']=np.zeros(n,np.int32)
    reason=np.where(valid,REASON_BITS['GROUND_UNAVAILABLE'],REASON_BITS['INVALID_XYZ']).astype(np.uint32)
    gd=_ground_diagnostics(metadata);coef=np.asarray(gd.get('plane_z_ax_by_c',[]),float)
    diag={'module':'d1_ground_clutter','status':'ABSTAIN','semantics':'display candidates only; no material or production occupancy decision','original_labels_unchanged':True,'reason_bits':REASON_BITS,'config':cfg,'clusters':[],'source_plane_reliable':bool(gd.get('reliable',False)),'local_fit_cells_accepted':0,'local_fit_cells_attempted':0,'full_ball_count_radii_m':[cfg['small_radius_m'],cfg['large_radius_m']]}
    anchor_ok=bool(gd.get('reliable',False))and coef.shape==(3,)and np.isfinite(coef).all()
    av=np.asarray(arrays.get('ground__ground_available',np.zeros(n,bool)),bool)&valid
    av&=anchor_ok
    if anchor_ok:
        global_z=xyz[:,0]*coef[0]+xyz[:,1]*coef[1]+coef[2]
        global_h=xyz[:,2]-global_z
        av&=np.isfinite(global_h)
        new['d1__ground_available']=av.copy();new['d1__global_anchor_height'][av]=global_h[av]
        correction=np.zeros(n,float);fitmad=np.full(n,np.nan);support=np.zeros(n,np.int16);used=np.zeros(n,bool)
        idx=np.flatnonzero(av);seed_idx=np.flatnonzero(av&(global_h>=cfg['seed_lower_m'])&(global_h<=cfg['seed_upper_m']))
        if len(seed_idx):
            seed_cells=np.floor(xyz[seed_idx,:2]/cfg['local_cell_m']).astype(np.int64)
            unique,inverse=np.unique(seed_cells,axis=0,return_inverse=True);order=np.argsort(inverse,kind='stable');groups=np.split(order,np.flatnonzero(np.diff(inverse[order]))+1)
            centers=[];offsets=[]
            for group in groups:
                if len(group)>=cfg['min_seed_points_per_cell']:
                    cell=seed_cells[group[0]];centers.append((cell+.5)*cfg['local_cell_m']);offsets.append(np.quantile(global_h[seed_idx[group]],cfg['seed_quantile']))
            if len(centers)>=cfg['min_local_seed_cells']:
                centers=np.asarray(centers);offsets=np.asarray(offsets);tree=cKDTree(centers)
                cells,point_cell=np.unique(np.floor(xyz[idx,:2]/cfg['local_cell_m']).astype(np.int64),axis=0,return_inverse=True)
                targets=(cells+.5)*cfg['local_cell_m'];neighbors=tree.query_ball_point(targets,cfg['local_radius_m'])
                cell_order=np.argsort(point_cell,kind='stable');point_groups=np.split(cell_order,np.flatnonzero(np.diff(point_cell[cell_order]))+1)
                for cell_id,group in enumerate(point_groups):
                    ni=np.asarray(neighbors[cell_id],int);diag['local_fit_cells_attempted']+=1
                    if len(ni)<cfg['min_local_seed_cells']:continue
                    xy=centers[ni]-targets[cell_id];quadrants=(xy[:,0]>=0).astype(int)+2*(xy[:,1]>=0)
                    if np.min(np.ptp(xy,axis=0))<cfg['min_xy_span_m']or len(np.unique(quadrants))<cfg['min_local_quadrants']:continue
                    design=np.column_stack([xy,np.ones(len(xy))])
                    if np.linalg.matrix_rank(design)<3:continue
                    coef_r=np.linalg.lstsq(design,offsets[ni],rcond=None)[0];res=np.abs(offsets[ni]-design@coef_r);keep=res<=cfg['local_inlier_residual_m']
                    if keep.sum()<cfg['min_local_seed_cells']:continue
                    coef_r=np.linalg.lstsq(design[keep],offsets[ni][keep],rcond=None)[0];mad=float(np.median(np.abs(offsets[ni][keep]-design[keep]@coef_r)))
                    if mad>cfg['max_local_fit_mad_m']or np.linalg.norm(coef_r[:2])>cfg['max_local_slope']or abs(coef_r[2])>cfg['max_local_correction_m']:continue
                    ids=idx[group];pred=(xyz[ids,:2]-targets[cell_id])@coef_r[:2]+coef_r[2]
                    safe=np.abs(pred)<=cfg['max_local_correction_m'];ids=ids[safe];pred=pred[safe]
                    correction[ids]=pred;fitmad[ids]=mad;support[ids]=min(int(keep.sum()),32767);used[ids]=True;diag['local_fit_cells_accepted']+=1
        h=global_h-correction
        new['d1__local_height'][av]=h[av];new['d1__ground_z'][av]=(global_z+correction)[av]
        new['d1__local_ground_correction'][av]=correction[av];new['d1__local_fit_mad'][av]=fitmad[av];new['d1__local_seed_support_count']=support;new['d1__local_model_used']=used
        reason[av]=np.where(used[av],REASON_BITS['LOCAL_MODEL_USED'],REASON_BITS['GLOBAL_ANCHOR_FALLBACK'])
        # Broad near-ground components are diagnostics, not material classes.
        candidates=np.flatnonzero(av&(h>cfg['cluster_min_height_m'])&(h<=cfg['cluster_max_height_m']))
        if len(candidates):
            scale=np.array([cfg['cluster_xy_voxel_m']]*2+[cfg['cluster_z_voxel_m']]);vox=np.floor(xyz[candidates]/scale).astype(np.int64);uv,inv=np.unique(vox,axis=0,return_inverse=True)
            pairs=cKDTree(uv).query_pairs(1.74,output_type='ndarray')
            graph=coo_matrix((np.ones(len(pairs)*2),(np.r_[pairs[:,0],pairs[:,1]],np.r_[pairs[:,1],pairs[:,0]])),shape=(len(uv),len(uv))).tocsr()if len(pairs)else coo_matrix((len(uv),len(uv))).tocsr()
            ncomp,comp=connected_components(graph,directed=False);point_comp=comp[inv]
            ground_touch=np.flatnonzero(av&(np.abs(h)<=cfg['contact_ground_band_m']))
            distance=cKDTree(xyz[ground_touch]).query(xyz[candidates],k=1,workers=cfg['workers'])[0]if len(ground_touch)else np.full(len(candidates),np.inf)
            all_tree=cKDTree(xyz[valid]);small=all_tree.query_ball_point(xyz[candidates],cfg['small_radius_m'],return_length=True,workers=cfg['workers']);large=all_tree.query_ball_point(xyz[candidates],cfg['large_radius_m'],return_length=True,workers=cfg['workers'])
            new['d1__small_ball_count'][candidates]=small;new['d1__large_ball_count'][candidates]=large
            g_available=np.asarray(arrays.get('geometry__scan_available',np.zeros(n,bool)),bool)&np.asarray(arrays.get('geometry__spatial_available',np.zeros(n,bool)),bool)
            hard_surface=g_available&(np.asarray(arrays.get('geometry__scan_surface_score',np.full(n,np.nan)))>=cfg['hard_scan_surface_min'])&(np.asarray(arrays.get('geometry__spatial_surface_score',np.full(n,np.nan)))>=cfg['hard_spatial_surface_min'])
            order=np.argsort(point_comp,kind='stable');groups=np.split(order,np.flatnonzero(np.diff(point_comp[order]))+1)
            for group in groups:
                ids=candidates[group];count=len(ids);q05,q10,q95=np.quantile(h[ids],[.05,.10,.95]);lateral=float(np.max(np.ptp(xyz[ids,:2],axis=0)));vertical=float(q95-q05);contact=float(np.mean(distance[group]<=cfg['contact_radius_m']));multi=float(np.mean((small[group]>=cfg['min_small_ball_count'])&(large[group]>=cfg['min_large_ball_count'])));ga=float(np.mean(g_available[ids]));hs=float(np.mean(hard_surface[ids]));cid=int(point_comp[group[0]])
                compact=bool(count>=cfg['hard_min_points']and lateral<=cfg['compact_max_span_m']and q95>=cfg['compact_min_height_m']);tall=bool(count>=cfg['hard_min_points']and(vertical>=cfg['hard_vertical_span_m']or q95>=cfg['hard_high_quantile_m']));surface=bool(count>=cfg['hard_min_points']and hs>=cfg['hard_surface_fraction_min']);unavailable_protect=ga<cfg['min_geometry_available_fraction'];sparse_protect=count<cfg['hard_min_points'];protected=compact or tall or surface or unavailable_protect or sparse_protect
                if protected:new['d1__hard_structure_protect_mask'][ids]=True
                # Existing point-level hard evidence is never diluted by a larger mixed cluster.
                direct_hard=ids[hard_surface[ids]];new['d1__hard_structure_protect_mask'][direct_hard]=True;reason[direct_hard]|=REASON_BITS['SURFACE_STRUCTURE_PROTECT']
                if sparse_protect:reason[ids]|=REASON_BITS['SPARSE_COMPONENT_PROTECT']
                for flag,name in [(compact,'COMPACT_STRUCTURE_PROTECT'),(tall,'VERTICAL_STRUCTURE_PROTECT'),(surface,'SURFACE_STRUCTURE_PROTECT'),(contact>=cfg['contact_fraction_min'],'GROUND_CONNECTED'),(vertical<=cfg['clutter_max_vertical_span_m'],'THIN_CLUSTER'),(multi>=cfg['multiscale_support_fraction_min'],'FULL_BALL_MULTISCALE_SUPPORT')]:
                    if flag:reason[ids]|=REASON_BITS[name]
                if ga<cfg['min_geometry_available_fraction']:reason[ids]|=REASON_BITS['GEOMETRY_UNAVAILABLE_RETAIN']
                eligible=(count>=cfg['cluster_min_points']and lateral>=cfg['clutter_min_lateral_span_m']and vertical<=cfg['clutter_max_vertical_span_m']and q10<=cfg['clutter_base_height_max_m']and contact>=cfg['contact_fraction_min']and multi>=cfg['multiscale_support_fraction_min']and ga>=cfg['min_geometry_available_fraction']and not protected)
                new['d1__low_clutter_eligible_mask'][ids]=eligible&~new['d1__hard_structure_protect_mask'][ids]
                new['d1__cluster_id'][ids]=cid;new['d1__cluster_point_count'][ids]=count
                for name,value in [('lateral_span',lateral),('vertical_span',vertical),('ground_contact_fraction',contact),('multiscale_support_fraction',multi),('geometry_available_fraction',ga),('hard_surface_fraction',hs)]:new['d1__cluster_'+name][ids]=value
                new['d1__low_clutter_score'][ids]=float(min(contact,multi,max(0,1-vertical/max(cfg['clutter_max_vertical_span_m'],1e-9))))
                diag['clusters'].append({'cluster_id':cid,'count':count,'lateral_span_m':lateral,'vertical_p95_p05_m':vertical,'height_p10_m':float(q10),'height_p95_m':float(q95),'ground_contact_fraction':contact,'multiscale_support_fraction':multi,'geometry_available_fraction':ga,'hard_surface_fraction':hs,'compact_protect':compact,'vertical_protect':tall,'surface_protect':surface,'geometry_unavailable_protect':bool(unavailable_protect),'sparse_component_protect':bool(sparse_protect),'display_clutter_eligible':bool(eligible),'material_identity':'UNKNOWN','first_raw_slots':[int(x)for x in np.asarray(arrays['raw_slot_id'])[ids[:8]]]})
        diag['status']='OK'if av.any()else'ABSTAIN'
    combined={**arrays,**new}
    core,clutter,strict,display=_threshold_masks(new,valid,cfg['ground_lower_m'],cfg['ground_upper_m'])
    new.update(d1__ground_core_mask=core,d1__low_clutter_mask=clutter,d1__nonground_strict_mask=strict,d1__nonground_display_mask=display,d1__risk_unknown_mask=valid&~core)
    reason[core]|=REASON_BITS['GROUND_CORE_CANDIDATE'];reason[clutter]|=REASON_BITS['LOW_CLUTTER_DISPLAY_CANDIDATE'];reason[valid&~core]|=REASON_BITS['MATERIAL_RISK_UNKNOWN'];new['d1__reason_code']=reason
    av=new['d1__ground_available'];h=new['d1__local_height'];new['d1__ground_core_score'][av]=np.clip(1-np.abs(h[av])/max(abs(cfg['ground_lower_m']),cfg['ground_upper_m']),0,1)
    diag.update(counts={'finite':int(valid.sum()),'ground_available':int(av.sum()),'local_model_used':int(new['d1__local_model_used'].sum()),'ground_core':int(core.sum()),'low_clutter':int(clutter.sum()),'nonground_strict':int(strict.sum()),'nonground_display':int(display.sum()),'hard_structure_protected':int(new['d1__hard_structure_protect_mask'].sum()),'risk_unknown':int(new['d1__risk_unknown_mask'].sum())},elapsed_ms=(time.perf_counter()-started)*1000,score_semantics='debug support measures, not calibrated probabilities',fallback='reliable global anchor within original available region, otherwise unavailable; all unavailable finite slots retained')
    return {'arrays':{**arrays,**new},'diagnostics':diag}
