"""Pure V1-D debug layer payloads. Native Noetic compatible; no FrameData IO."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import importlib.util
import hashlib,json
import numpy as np

DROOT=Path(__file__).resolve().parents[1]
_spec=importlib.util.spec_from_file_location('frozen_c_ros_sequence',DROOT.parent/'v1c/opdf_c/sequence_io.py')
_c=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_c)
FIELDS=_c.FIELDS;PALETTE=_c.PALETTE;STAGE2=_c.STAGE2
BASE_TOPICS=list(_c.TOPICS)
C_TOPICS=['/opdf_v1/aerosol_suspect','/opdf_v1/entity_optical_conflict']
EXTRA_NAMES=('ground_core','low_clutter_candidate','nonground_strict','nonground_display_only',
             'b_entity','b_aerosol','entity_evidence_change','aerosol_evidence_change',
             'hard_structure_protect','low_risk_unknown')
TOPICS=BASE_TOPICS+C_TOPICS+['/opdf_v1/'+name for name in EXTRA_NAMES]
C_AUX_KEYS=('aerosol_suspect_mask','aerosol_suspect_available_mask','suspect_uniform_low_mask',
            'entity_optical_conflict_mask','suspect_protected_mask','suspect_evidence_count','suspect_reason_code')
DECISION_KEYS=('labels','score_e','score_a','available_e','available_a','reason_code',
               'retain_solid_mask','retain_with_ground_mask','aerosol_candidate_mask')
DTYPE=np.dtype({'names':['x','y','z','intensity','rgb_bits','raw_slot_id'],
       'formats':['<f4','<f4','<f4','<f4','<u4','<u4'],
       'offsets':[0,4,8,12,16,20],'itemsize':24})
COLORS={'ground_core':0x00969AAA,'low_clutter_candidate':0x00FFDC28,
        'hard_structure_protect':0x0028E6FF,'low_risk_unknown':0x00B478E6,
        'aerosol_suspect':0x00FFE600,'entity_optical_conflict':0x00FFFFFF}
CHANGE_COLORS={'new_E':0x0000FFFF,'old_E_no_longer_E':0x00FF32B4,
               'new_A':0x00FF1E1E,'old_A_no_longer_A':0x0032E650,
               'score_increase':0x00FFB432,'score_decrease':0x004664FF}


def finite_mask(arrays):
    return np.asarray(arrays['valid_xyz_mask'],bool)&np.isfinite(arrays['xyz']).all(1)


def checked_mask(arrays,key):
    v=np.asarray(arrays[key])
    if v.shape!=(len(arrays['xyz']),) or v.dtype.kind!='b':raise ValueError(key+' must be slot-aligned bool')
    if np.any(v&~finite_mask(arrays)):raise ValueError(key+' marks invalid original slots')
    return v


def guard_masks(arrays,guard=None):
    strict=checked_mask(arrays,'d1__nonground_strict_mask')
    clutter=checked_mask(arrays,'d1__low_clutter_mask')
    if guard is None:
        return dict(suppressible=np.zeros(len(strict),bool),deferred=clutter.copy(),display=strict.copy(),status='GUARD_UNAVAILABLE_NO_SUPPRESSION')
    n=len(strict)
    for k in ('low_clutter_suppressible_mask','low_clutter_deferred_mask','nonground_guarded_display_mask'):
        if k not in guard or np.asarray(guard[k]).shape!=(n,) or np.asarray(guard[k]).dtype.kind!='b':
            raise ValueError('Missing/malformed exact incremental guard '+k)
    sup=guard['low_clutter_suppressible_mask'];defer=guard['low_clutter_deferred_mask'];display=guard['nonground_guarded_display_mask']
    if np.any(sup&~clutter) or not np.array_equal(defer,clutter&~sup) or not np.array_equal(display,strict&~sup):
        raise ValueError('Guard partition/display contract differs from source D1')
    available=(np.asarray(arrays['geometry__scan_available'],bool)&np.asarray(arrays['geometry__spatial_available'],bool)
               &np.asarray(arrays['d1__ground_available'],bool)&finite_mask(arrays))
    if np.any(sup&~available):raise ValueError('Guard attempts suppression with unavailable per-point geometric/ground evidence')
    if np.any(sup&checked_mask(arrays,'d1__hard_structure_protect_mask')):raise ValueError('Guard suppresses protected structure')
    return dict(suppressible=sup,deferred=defer,display=display,status='SOURCE_VERIFIED_POINTWISE_GUARD')


def pack(arrays,mask,rgb):
    valid=finite_mask(arrays);mask=np.asarray(mask,bool)
    if mask.shape!=valid.shape or np.any(mask&~valid):raise ValueError('Debug mask contains invalid/nonexistent echo')
    ids=np.asarray(arrays['raw_slot_id'])[mask]
    if ids.dtype.kind not in 'ui' or np.any(ids<0)or np.any(ids>np.iinfo(np.uint32).max):raise ValueError('Raw slot IDs exceed exact uint32 export')
    points=np.zeros(int(mask.sum()),dtype=DTYPE)
    for i,key in enumerate(('x','y','z')):points[key]=arrays['xyz'][mask,i]
    points['intensity']=np.asarray(arrays['intensity'])[mask]
    points['rgb_bits']=np.uint32(rgb) if np.isscalar(rgb) else np.asarray(rgb,np.uint32)[mask]
    points['raw_slot_id']=ids.astype('<u4')
    return points


def label_colors(labels):
    packed=np.zeros(len(labels),np.uint32)
    for value,rgb in PALETTE.items():packed[np.asarray(labels)==value]=(rgb[0]<<16)|(rgb[1]<<8)|rgb[2]
    return packed


def baseline(arrays,key):
    return np.asarray(arrays.get('b__'+key,arrays[key]))


def evidence_change(arrays,which,threshold=.1):
    if which not in ('e','a'):raise ValueError('Evidence kind must be e/a')
    valid=finite_mask(arrays);label=1 if which=='e' else 2
    old=baseline(arrays,'labels')==label;new=np.asarray(arrays['labels'])==label
    before=baseline(arrays,'score_'+which);after=np.asarray(arrays['score_'+which])
    available=(baseline(arrays,'available_'+which).astype(bool)&np.asarray(arrays['available_'+which],bool)
               &np.isfinite(before)&np.isfinite(after)&valid)
    if not np.isfinite(threshold)or threshold<=0:raise ValueError('Debug score delta threshold must be finite positive')
    delta=np.zeros(len(valid),float);delta[available]=after[available]-before[available]
    increase=available&(delta>=threshold);decrease=available&(delta<=-threshold)
    newly=valid&new&~old;lost=valid&old&~new
    mask=newly|lost|increase|decrease
    color=np.zeros(len(valid),np.uint32)
    color[increase]=CHANGE_COLORS['score_increase'];color[decrease]=CHANGE_COLORS['score_decrease']
    color[newly]=CHANGE_COLORS['new_E' if which=='e' else 'new_A']
    color[lost]=CHANGE_COLORS['old_E_no_longer_E' if which=='e' else 'old_A_no_longer_A']
    return pack(arrays,mask,color),dict(label_appear=int(newly.sum()),label_disappear=int(lost.sum()),
        score_increase=int(increase.sum()),score_decrease=int(decrease.sum()),score_delta_debug_threshold=threshold,
        scores_not_calibrated_probabilities=True,physical_loss_or_correctness_not_inferred=True)


def build_layers(arrays,guard=None,score_delta_threshold=.1):
    """All 22 derived topics (RAW is separately exact cached PointCloud2)."""
    valid=finite_mask(arrays);labels=np.asarray(arrays['labels']);colors=label_colors(labels)
    messages={topic:_c.derived_points(arrays,topic.rsplit('/',1)[1]) for topic in BASE_TOPICS if not topic.endswith('/raw')}
    for name,key in (('aerosol_suspect','aerosol_suspect_mask'),('entity_optical_conflict','entity_optical_conflict_mask')):
        messages['/opdf_v1/'+name]=pack(arrays,checked_mask(arrays,key),COLORS[name])
    checked=guard_masks(arrays,guard)
    masks={'ground_core':checked_mask(arrays,'d1__ground_core_mask'),
      'low_clutter_candidate':checked_mask(arrays,'d1__low_clutter_mask'),
      'nonground_strict':checked_mask(arrays,'d1__nonground_strict_mask'),
      'nonground_display_only':checked['display'],
      'b_entity':valid&(baseline(arrays,'labels')==1),'b_aerosol':valid&(baseline(arrays,'labels')==2),
      'hard_structure_protect':checked_mask(arrays,'d1__hard_structure_protect_mask'),
      'low_risk_unknown':checked_mask(arrays,'d1__risk_unknown_mask')}
    for name,mask in masks.items():
        rgb=COLORS.get(name,colors)
        if name in ('b_entity','b_aerosol'):rgb=label_colors(baseline(arrays,'labels'))
        messages['/opdf_v1/'+name]=pack(arrays,mask,rgb)
    e,ed=evidence_change(arrays,'e',score_delta_threshold);a,ad=evidence_change(arrays,'a',score_delta_threshold)
    messages['/opdf_v1/entity_evidence_change']=e;messages['/opdf_v1/aerosol_evidence_change']=a
    if set(messages)!=set(TOPICS)-{'/opdf_v1/raw'}:raise ValueError('Derived topic set differs from explicit allowlist')
    return messages,dict(guard_status=checked['status'],candidate_clutter_count=int(masks['low_clutter_candidate'].sum()),
        suppressible_count=int(checked['suppressible'].sum()),deferred_count=int(checked['deferred'].sum()),
        entity_evidence_change=ed,aerosol_evidence_change=ad)


def schema():
    s=_c.schema();s['topics']=TOPICS
    s.update(method='OPDF-V1-D diagnostic layers',score_delta_threshold=.1,
       source_old_heatmaps='frozen B optical/scan/spatial evidence, not new D geometry or calibrated probabilities',
       colors_bits={k:hex(v) for k,v in COLORS.items()},evidence_change_colors={k:hex(v) for k,v in CHANGE_COLORS.items()},
       d_semantics={'ground_core':'D1 independent diagnostic core; NOT labels G or free space',
        'low_clutter_candidate':'all D1 candidate clutter, NOT authorized suppression',
        'nonground_strict':'finite minus D1 core',
        'nonground_display_only':'strict minus verified per-point suppressible only; no guard => strict unchanged',
        'b_entity':'frozen B E only','b_aerosol':'frozen B A only',
        'entity_evidence_change':'B-D E label xor OR jointly available score delta >=.1; old E->U is retained, not physical removal',
        'aerosol_evidence_change':'B-D A label xor OR jointly available score delta >=.1; new A is candidate not proven particle',
        'hard_structure_protect':'D1 protective structure evidence, not confirmed material',
        'low_risk_unknown':'D1 risk/unknown geometry; never free space'},
       review_only_C_layers={'aerosol_suspect':'frozen C suspect mask, never direct deletion',
                             'entity_optical_conflict':'frozen C E/optical conflict, not truth'},
       controls_copied=False,synthetic_echoes_generated=False)
    return s


def filehash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_npz(path):
    with np.load(path,allow_pickle=False)as z:return {k:z[k]for k in z.files}


def identity(meta,entry):
    m=meta.get('metadata',meta)
    for key in ('seq','header_stamp_ns','record_stamp_ns'):
        if m.get(key)!=entry[key]:raise ValueError('Source measurement identity mismatch: '+key)
    if m.get('raw_message_sha256')!=entry['sha256']:raise ValueError('Source raw message sha mismatch')


def equal_bits(a,b):
    return a.shape==b.shape and a.dtype==b.dtype and np.ascontiguousarray(a).tobytes()==np.ascontiguousarray(b).tobytes()


def load_frame(frame_dir,entry,c_aux_run,guard_dir=None,d1_source_run=None):
    """Bind source, frozen C auxiliary fields and optional prefixed guard to exact slots."""
    source=Path(frame_dir)/(entry['key']+'.npz');side=source.with_suffix('.json')
    meta=json.loads(side.read_text());identity(meta,entry);arrays=load_npz(source)
    proof={'source_npz':str(source.resolve()),'source_npz_sha256':filehash(source),
           'source_json_sha256':filehash(side),'measurement':{k:entry[k]for k in ('seq','header_stamp_ns','record_stamp_ns','sha256')}}
    cp=Path(c_aux_run)/'frames'/(entry['key']+'.npz');cj=cp.with_suffix('.json')
    identity(json.loads(cj.read_text()),entry);c=load_npz(cp)
    for key in ('xyz','intensity','valid_xyz_mask','raw_slot_id'):
        if not equal_bits(arrays[key],c[key]):raise ValueError('Frozen C measurement/slot mismatch: '+key)
    original_keys=set(c)-set(C_AUX_KEYS)
    if len(original_keys)!=48:raise ValueError('Frozen C source is not original B48 plus C7')
    for key in original_keys:
        candidate=arrays.get('b__'+key,arrays.get(key))if key in DECISION_KEYS else arrays.get(key)
        if candidate is None or not equal_bits(candidate,c[key]):raise ValueError('Frozen original B evidence differs: '+key)
    for key in C_AUX_KEYS:
        if key in arrays and not equal_bits(arrays[key],c[key]):raise ValueError('Frozen C auxiliary altered: '+key)
        arrays[key]=c[key]
    proof.update(frozen_c_npz_sha256=filehash(cp),frozen_c_json_sha256=filehash(cj),frozen_c_aux_verified=True,frozen_B48_verified=True)
    guard=None
    if guard_dir is not None:
        if d1_source_run is None:raise ValueError('Explicit guard requires --d1-source-run')
        gp=Path(guard_dir)/(entry['key']+'.npz');gj=gp.with_suffix('.json');gm=json.loads(gj.read_text())
        d1=Path(d1_source_run)/'frames'/(entry['key']+'.npz');dj=d1.with_suffix('.json')
        if filehash(d1)!=gm['source_d1_npz_sha256'] or filehash(dj)!=gm['source_d1_json_sha256']:
            raise ValueError('Guard source D1 SHA mismatch')
        identity(json.loads(dj.read_text()),entry)
        for key in ('seq','header_stamp_ns','record_stamp_ns'):
            if gm.get(key)!=entry[key]:raise ValueError('Guard measurement identity mismatch')
        original=load_npz(d1);g=load_npz(gp)
        for key in original:
            # D2 may exchange decision arrays, all D1 diagnostic/measurement arrays must survive.
            if key.startswith('d1__') or key in ('xyz','intensity','raw_slot_id','valid_xyz_mask'):
                if not equal_bits(arrays[key],original[key]):raise ValueError('Guard D1 domain mismatch: '+key)
        if not equal_bits(g['raw_slot_id'],arrays['raw_slot_id']):raise ValueError('Guard raw slots mismatch')
        names=('low_clutter_suppressible_mask','low_clutter_deferred_mask','nonground_guarded_display_mask')
        guard={k:g['d1__'+k]for k in names}
        proof['guard']={'npz_sha256':filehash(gp),'json_sha256':filehash(gj),'source_d1_npz_sha256':filehash(d1),
                        'source_d1_json_sha256':filehash(dj),'prefixed_keys_explicitly_normalized':True}
    layers,diagnostics=build_layers(arrays,guard)
    return arrays,layers,dict(proof=proof,diagnostics=diagnostics)
