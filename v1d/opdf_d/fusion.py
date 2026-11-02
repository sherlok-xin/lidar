"""D2 geometry-only/fusion candidates. No GT, original-B classes explicitly saved."""
from __future__ import annotations
import time
import numpy as np

VERSION='OPDF-V1-D2-fusion/0.1.0'
REASONS={'INVALID':1,'B_G_FIXED':2,'OLD_LOW_PROTECTED':4,'OLD_NEAR_PROTECTED':8,
 'OLD_EDGE_PROTECTED':16,'D1_HARD_PROTECTED':32,'MULTISCALE_UNAVAILABLE':64,
 'NEW_STABLE_STRUCTURE':128,'NEW_VOLUME':256,'OPTICAL_RELATIVE_CUE':512,
 'OPTICAL_UNIFORM_CUE':1024,'STRUCTURE_VOLUME_CONFLICT':2048,
 'E_TO_U_REJECT':4096,'A_TO_U_RECALL':8192,'U_TO_E_CANDIDATE':16384,
 'U_TO_A_CANDIDATE':32768,'D1_GROUND_REFERENCE_UNAVAILABLE':65536,'B_CLASS_RETAINED':131072}
STANDARD_FIELDS=('labels','score_e','score_a','available_e','available_a','reason_code',
                 'retain_solid_mask','retain_with_ground_mask','aerosol_candidate_mask')


def fuse(arrays, multiscale_result, config, *, ablation='fusion'):
    if ablation not in ('geometry_only','fusion'):raise ValueError('Unknown D2 ablation')
    start=time.perf_counter();cfg=config['d2'];ms=multiscale_result['arrays']
    n=len(arrays['xyz']);valid=np.asarray(arrays['valid_xyz_mask'],bool)&np.isfinite(arrays['xyz']).all(1)
    old=np.asarray(arrays['labels'],np.uint8);ground=valid&(old==4)
    low=arrays['ground__low_object_mask']&valid
    near=arrays['ground__near_ground_mask']&valid&~ground
    edge=arrays['geometry__edge_protect_mask']&valid
    hard_d1=arrays['d1__hard_structure_protect_mask']&valid
    protect=low|near|edge|hard_d1
    reliable_ground=arrays['d1__ground_available']&np.isfinite(arrays['d1__local_height'])&valid
    all_scales=ms['d2__ms_available'].all(1)&valid
    usable_structure=(ms['d2__ms_available'].sum(1)>=2)&valid
    hard_structure=ms['d2__hard_plane_support']|ms['d2__hard_line_support']
    any_structure=ms['d2__hard_structure_any_scale']
    volume=ms['d2__volume_candidate']&valid
    relative=(arrays['optical__optical_available']&np.isfinite(arrays['optical__optical_weak_score'])&
              (arrays['optical__optical_weak_score']>=cfg['optical_relative_weak_min']))
    uniform=(valid&~ground&arrays['optical__optical_available']&np.isfinite(arrays['intensity'])&
       (arrays['intensity']<=cfg['uniform_intensity_max'])&
       (arrays['optical__local_intensity_median']<=cfg['uniform_local_median_max'])&
       (np.abs(arrays['optical__relative_intensity_z'])<=cfg['uniform_abs_relative_z_max']))
    if not cfg['uniform_low_enabled']:uniform[:]=False
    optical=relative|uniform
    scan_entity=(arrays['geometry__scan_available']&np.isfinite(arrays['geometry__scan_surface_score'])&
                 (arrays['geometry__scan_surface_score']>=cfg['entity_scan_surface_min']))
    # Conflicting positive geometry rejects old E to retained U. Missing evidence
    # alone never proves an old E is false. Never make direct E -> A.
    demote_e=valid&(old==1)&all_scales&volume&~hard_structure
    recall_a=valid&(old==2)&(protect|any_structure)
    labels=old.copy();labels[~valid]=0;labels[ground]=4
    labels[demote_e|recall_a]=3
    new_e=valid&(old==3)&~ground&~low&~near&hard_structure&scan_entity&~volume
    labels[new_e]=1
    eligible_a=valid&(old==3)&~ground&reliable_ground&volume&~any_structure&~protect
    if cfg['new_A_requires_all_scales_available']:eligible_a&=all_scales
    new_a=eligible_a&optical if ablation=='fusion' else np.zeros(n,bool)
    labels[new_a]=2
    # Scores expose evidence, never posterior probability. Existing A keeps its
    # B score when no new geometric veto exists; new A has explicit D2 support.
    score_e=np.full(n,np.nan,np.float32);score_a=np.full(n,np.nan,np.float32)
    structure_score=np.maximum(ms['d2__ms_linearity'],ms['d2__ms_planarity'])
    surface_score=np.sum(np.where(ms['d2__ms_available'],structure_score,0),axis=1)/np.maximum(ms['d2__ms_available'].sum(1),1)
    score_e[usable_structure]=surface_score[usable_structure]
    volume_score=np.sum(np.where(ms['d2__ms_available'],ms['d2__ms_scattering'],0),axis=1)/np.maximum(ms['d2__ms_available'].sum(1),1)
    ava=(eligible_a & arrays['optical__optical_available'] &
         np.isfinite(arrays['optical__optical_weak_score'])) if ablation=='fusion' else np.zeros(n,bool)
    score_a[ava]=volume_score[ava]*np.where(uniform[ava],1.,np.clip(arrays['optical__optical_weak_score'][ava],0,1))
    old_a_retained=valid&(old==2)&~recall_a
    ava=ava|old_a_retained
    score_a[old_a_retained]=arrays['score_a'][old_a_retained]
    reason=np.zeros(n,np.uint32)
    for name,mask in [('INVALID',~valid),('B_G_FIXED',ground),('OLD_LOW_PROTECTED',low),
      ('OLD_NEAR_PROTECTED',near),('OLD_EDGE_PROTECTED',edge),('D1_HARD_PROTECTED',hard_d1),
      ('MULTISCALE_UNAVAILABLE',valid&~ground&~all_scales),('NEW_STABLE_STRUCTURE',hard_structure),
      ('NEW_VOLUME',volume),('OPTICAL_RELATIVE_CUE',relative),('OPTICAL_UNIFORM_CUE',uniform),
      ('STRUCTURE_VOLUME_CONFLICT',ms['d2__geometry_conflict']),('E_TO_U_REJECT',demote_e),
      ('A_TO_U_RECALL',recall_a),('U_TO_E_CANDIDATE',new_e),('U_TO_A_CANDIDATE',new_a),
      ('D1_GROUND_REFERENCE_UNAVAILABLE',valid&~ground&~reliable_ground),('B_CLASS_RETAINED',valid&(labels==old))]:
        reason[mask]|=REASONS[name]
    out={f'b__{key}':np.asarray(arrays[key]).copy() for key in STANDARD_FIELDS}
    out.update(labels=labels,score_e=score_e,score_a=score_a,available_e=usable_structure,
               available_a=ava,reason_code=reason,retain_solid_mask=(labels==1)|(labels==3),
               retain_with_ground_mask=(labels==1)|(labels==3)|(labels==4),aerosol_candidate_mask=labels==2)
    out.update({'d2__hard_protection_union':protect,'d2__optical_relative_cue':relative,
                'd2__optical_uniform_cue':uniform,'d2__new_A_eligible_geometry':eligible_a,
                'd2__new_A_mask':new_a,'d2__new_E_mask':new_e,'d2__E_to_U_mask':demote_e,
                'd2__A_to_U_mask':recall_a,'d2__changed_label_mask':labels!=old,
                'd2__fusion_reason_code':reason.copy()})
    violation={'protected_new_A':int((new_a&protect).sum()),'direct_E_to_A':int(((old==1)&(labels==2)).sum()),
               'B_G_changed':int(((old==4)&(labels!=4)).sum()),'INVALID_changed':int((~valid&(labels!=0)).sum()),
               'geometry_only_new_A':int(new_a.sum()) if ablation=='geometry_only' else 0}
    if any(violation.values()):raise AssertionError(violation)
    return {'arrays':out,'diagnostics':{'version':VERSION,'ablation':ablation,'status':'OK',
     'reason_bits':REASONS,'invariant_violations':violation,
     'new_E':int(new_e.sum()),'new_A':int(new_a.sum()),'E_to_U':int(demote_e.sum()),'A_to_U':int(recall_a.sum()),
     'optical_cue_not_material_truth':True,'G_source':'B original fixed; D1 GroundCore is separate display layer',
     'C_aux_source':'original B48, unchanged C diagnostic domain',
     'new_A_hypothesis':'multiscale volume + optical cue, explicitly replaces B scan-AND; no stable structure or protection',
     'score_semantics':'heuristic evidence, not posterior; no GT tuning',
     'counts':{name:int((labels==value).sum()) for name,value in [('INVALID',0),('E',1),('A',2),('U',3),('G',4)]},
     'fusion_ms':(time.perf_counter()-start)*1000}}
