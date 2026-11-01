"""Frozen V1-B gate reconstruction from saved features. Diagnostic only, no filtering."""
from __future__ import annotations

import numpy as np

VERSION = 'v1c-stage3-gates/1.0'
LABELS = {'INVALID': 0, 'E': 1, 'A': 2, 'U': 3, 'G': 4}
REASONS = {'INVALID_XYZ': 1, 'GROUND_ACCEPTED': 2, 'LOW_OBJECT_PROTECTED': 4,
 'EDGE_OR_LINE_PROTECTED': 8, 'OPTICAL_WEAK': 16, 'SCAN_DISCONTINUOUS': 32,
 'SPATIAL_DIFFUSE': 64, 'SOLID_AGREEMENT': 128, 'OPTICAL_UNAVAILABLE': 256,
 'SCAN_UNAVAILABLE': 512, 'SPATIAL_UNAVAILABLE': 1024, 'GROUND_UNRELIABLE': 2048,
 'MATERIAL_CONFLICT': 4096, 'INSUFFICIENT_AGREEMENT': 8192,
 'NEAR_GROUND_PROTECTED': 16384, 'AEROSOL_MULTI_EVIDENCE': 32768}
ROI_CANDIDATES = {
 'vehicle_structure_candidate': [-7, 12, -6, 6, -.8, 3.5],
 'near_ground_rough_vegetation_candidate': [3, 18, -16, -6, -1.8, -.5],
 'aerosol_surface_ambiguity': [7, 10, 1, 4, -1, 2.5],
}


def _array(arrays, key, n, dtype=float):
    if key not in arrays:
        raise ValueError(f'Missing frozen feature {key}')
    a = np.asarray(arrays[key], dtype=dtype)
    if a.shape != (n,):
        raise ValueError(f'Non slot-aligned {key}: {a.shape}')
    return a


def reconstruct_gates(arrays, config):
    """Reconstruct exact decision predicates; never infers material ground truth."""
    xyz = np.asarray(arrays['xyz'])
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError('xyz must be Nx3')
    n = len(xyz)
    raw = _array(arrays, 'raw_slot_id', n, np.uint64)
    if len(np.unique(raw)) != n:
        raise ValueError('Duplicate original slot IDs')
    cfg = config['decision']
    a = lambda key, dtype=float: _array(arrays, key, n, dtype)
    valid = a('valid_xyz_mask', bool) & np.isfinite(xyz).all(axis=1)
    gav = a('ground__ground_available', bool) & valid
    gm = a('ground__ground_mask', bool) & gav
    low = a('ground__low_object_mask', bool) & valid
    near = a('ground__near_ground_mask', bool) & valid & ~gm
    edge = a('geometry__edge_protect_mask', bool) & valid
    weak = a('optical__optical_weak_score')
    surf = a('geometry__scan_surface_score')
    disc = a('geometry__scan_discontinuity_score')
    solid_score = a('geometry__spatial_surface_score')
    diffuse = a('geometry__spatial_diffuse_score')
    ov = a('optical__optical_available', bool) & valid & np.isfinite(weak)
    sv = a('geometry__scan_available', bool) & valid & np.isfinite(surf) & np.isfinite(disc)
    pv = a('geometry__spatial_available', bool) & valid & np.isfinite(solid_score) & np.isfinite(diffuse)
    op = ov & (weak >= cfg['aerosol_optical_min'])
    sp = sv & (disc >= cfg['aerosol_scan_discontinuity_min'])
    pp = pv & (diffuse >= cfg['aerosol_spatial_diffuse_min'])
    all_available = ov & sv & pv
    available_e = sv & pv
    available_a = all_available.copy()
    if cfg['require_reliable_ground_for_aerosol']:
        available_a &= gav
    solid = available_e & (surf >= cfg['entity_scan_surface_min']) & (solid_score >= cfg['entity_spatial_surface_min'])
    triple = op & sp & pp
    protect = low | near | edge
    aerosol = available_a & triple & ~protect & ~solid & ~gm
    entity = solid & ~low & ~near & ~gm
    labels = np.where(valid, LABELS['U'], LABELS['INVALID']).astype(np.uint8)
    labels[gm] = LABELS['G']; labels[entity] = LABELS['E']; labels[aerosol] = LABELS['A']
    reason = np.zeros(n, np.uint32)
    flags = {'INVALID_XYZ': ~valid, 'GROUND_ACCEPTED': gm, 'LOW_OBJECT_PROTECTED': low,
     'NEAR_GROUND_PROTECTED': near, 'EDGE_OR_LINE_PROTECTED': edge,
     'OPTICAL_WEAK': op, 'SCAN_DISCONTINUOUS': sp, 'SPATIAL_DIFFUSE': pp,
     'SOLID_AGREEMENT': solid, 'OPTICAL_UNAVAILABLE': valid & ~ov,
     'SCAN_UNAVAILABLE': valid & ~sv, 'SPATIAL_UNAVAILABLE': valid & ~pv,
     'GROUND_UNRELIABLE': valid & ~gav, 'MATERIAL_CONFLICT': valid & op & (solid | protect),
     'INSUFFICIENT_AGREEMENT': valid & (labels == LABELS['U']), 'AEROSOL_MULTI_EVIDENCE': aerosol}
    for name, mask in flags.items():
        reason[mask] |= REASONS[name]
    score_e = np.full(n, np.nan, np.float32)
    score_a = np.full(n, np.nan, np.float32)
    score_e[available_e] = np.sqrt(np.clip(surf[available_e]*solid_score[available_e], 0, 1))
    score_a[available_a] = np.cbrt(np.clip(weak[available_a]*disc[available_a]*diffuse[available_a], 0, 1))
    result = dict(valid=valid, ground_available=gav, ground=gm, low=low, near=near,
                  edge=edge, protect=protect, optical_available=ov, scan_available=sv,
                  spatial_available=pv, optical_pass=op, scan_pass=sp, spatial_pass=pp,
                  all_available=all_available, available_a=available_a, available_e=available_e,
                  solid_support=solid, triple_pass=triple, aerosol=aerosol,
                  reconstructed_labels=labels, reconstructed_reason=reason,
                  reconstructed_score_e=score_e, reconstructed_score_a=score_a)
    result['availability_pattern'] = ov.astype(np.uint8)*4 + sv.astype(np.uint8)*2 + pv.astype(np.uint8)
    result['threshold_pattern'] = op.astype(np.uint8)*4 + sp.astype(np.uint8)*2 + pp.astype(np.uint8)
    result['protection_pattern'] = near.astype(np.uint8)*4 + low.astype(np.uint8)*2 + edge.astype(np.uint8)
    result['ground_requirement_enabled'] = bool(cfg['require_reliable_ground_for_aerosol'])
    return result


def check_reconstruction(arrays, gates):
    checks = {}
    for stored, reconstructed in [('labels','reconstructed_labels'), ('reason_code','reconstructed_reason'),
                                   ('available_a','available_a'), ('available_e','available_e')]:
        if stored not in arrays:
            raise ValueError(f'Missing frozen decision output {stored}')
        mismatch = np.asarray(arrays[stored]) != gates[reconstructed]
        checks[stored+'_mismatches'] = int(mismatch.sum())
    for stored, reconstructed in [('score_a','reconstructed_score_a'),('score_e','reconstructed_score_e')]:
        x, y = np.asarray(arrays[stored]), gates[reconstructed]
        mismatch = ~np.isclose(x, y, rtol=0, atol=0, equal_nan=True)
        checks[stored+'_mismatches'] = int(mismatch.sum())
    checks['exact_match'] = not any(checks.values())
    return checks


def counterfactuals(arrays, gates, config, delta=0.10):
    """One A-gate intervention at a time; no formal V1-C labels/deletion mask."""
    cfg = config['decision']
    specs = [('remove_near_A_protection','near',None), ('remove_low_A_protection','low',None),
             ('remove_edge_A_protection','edge',None), ('remove_ground_available_requirement','gav',None),
             ('optical_threshold_minus_0p10','optical',cfg['aerosol_optical_min']-delta),
             ('scan_threshold_minus_0p10','scan',cfg['aerosol_scan_discontinuity_min']-delta),
             ('spatial_threshold_minus_0p10','spatial',cfg['aerosol_spatial_diffuse_min']-delta)]
    out = {}
    for name, changed, threshold in specs:
        op, sp, pp = (gates[k].copy() for k in ['optical_pass','scan_pass','spatial_pass'])
        if changed == 'optical': op = gates['optical_available'] & (arrays['optical__optical_weak_score'] >= threshold)
        if changed == 'scan': sp = gates['scan_available'] & (arrays['geometry__scan_discontinuity_score'] >= threshold)
        if changed == 'spatial': pp = gates['spatial_available'] & (arrays['geometry__spatial_diffuse_score'] >= threshold)
        protection = np.zeros(len(op), bool)
        for key in ['near','low','edge']:
            if key != changed: protection |= gates[key]
        available = gates['all_available'].copy()
        if cfg['require_reliable_ground_for_aerosol'] and changed != 'gav':
            available &= gates['ground_available']
        candidate = available & op & sp & pp & ~protection & ~gates['solid_support'] & ~gates['ground']
        out[name] = {'candidate_A':candidate, 'added':candidate & ~gates['aerosol'],
                     'removed':gates['aerosol'] & ~candidate,
                     'changed_parameter':changed, 'new_threshold':threshold,
                     'diagnostic_only_no_deletion':True}
    return out


def _pattern(values, mask):
    return {format(k,'03b'):int(np.count_nonzero(mask & (values == k))) for k in range(8)}


def _quantile(a, mask):
    x = np.asarray(a)[mask]
    x = x[np.isfinite(x)]
    return {'finite_n':int(len(x)), 'q05_q25_q50_q75_q95': np.quantile(x,[.05,.25,.5,.75,.95]).tolist() if len(x) else None}


def statistics(arrays, gates, cfs, mask):
    valid = np.asarray(mask,bool) & gates['valid']
    nonground = valid & ~gates['ground']
    n = int(nonground.sum())
    count = lambda m:int(np.count_nonzero(m & nonground))
    report = {'scope_slots':int(np.count_nonzero(mask)), 'valid':int(valid.sum()), 'valid_nonG':n,
              'counts':{name:int(np.count_nonzero(mask & (arrays['labels'] == value))) for name,value in LABELS.items()},
              'gates':{}, 'availability_pattern_OSP':_pattern(gates['availability_pattern'],nonground),
              'threshold_pattern_OSP_unavailable_is_fail':_pattern(gates['threshold_pattern'],nonground),
              'threshold_pattern_OSP_all_available_only':_pattern(gates['threshold_pattern'],nonground & gates['all_available']),
              'protection_pattern_NLE_nonG':_pattern(gates['protection_pattern'],nonground),
              'protection_pattern_NLE_triple_pass':_pattern(gates['protection_pattern'],nonground & gates['triple_pass']),
              'all_available':count(gates['all_available']), 'triple_pass':count(gates['triple_pass']),
              'ground_available_required':gates['ground_requirement_enabled'],
              'triple_pass_missing_ground_reference':count(gates['triple_pass'] & ~gates['ground_available']),
              'solid_support':count(gates['solid_support']),
              'triple_pass_solid_conflict':count(gates['triple_pass'] & gates['solid_support']),
              'protection':{}, 'counterfactuals':{}, 'feature_summary':{}}
    for key in ['optical','scan','spatial']:
        available, passed = gates[key+'_available'], gates[key+'_pass']
        report['gates'][key] = {'available':count(available),'unavailable':count(~available),
                                'available_rate_nonG':count(available)/n if n else None,
                                'pass':count(passed),'fail_when_available':count(available & ~passed),
                                'pass_rate_available':count(passed)/count(available) if count(available) else None}
    for key in ['near','low','edge']:
        others = np.zeros(len(valid),bool)
        for other in ['near','low','edge']:
            if other != key:others |= gates[other]
        report['protection'][key] = {'all_nonG':count(gates[key]),
            'among_triple_pass':count(gates[key] & gates['triple_pass']),
            'only_this_protection_among_triple_pass':count(gates[key] & ~others & gates['triple_pass'])}
    for name, cf in cfs.items():
        report['counterfactuals'][name] = {'added_A_diagnostic':count(cf['added']),
            'removed_A_diagnostic':count(cf['removed']), 'new_threshold':cf['new_threshold'],
            'changed_parameter':cf['changed_parameter'], 'diagnostic_only_no_deletion':True}
    features = ['intensity','ground__ground_height','optical__relative_intensity_z',
        'optical__local_intensity_median','optical__local_intensity_mad','optical__optical_weak_score',
        'geometry__scan_surface_score','geometry__scan_discontinuity_score','geometry__spatial_surface_score',
        'geometry__spatial_diffuse_score','geometry__linearity','geometry__planarity','geometry__spatial_neighbor_count']
    for key in features:
        if key in arrays:report['feature_summary'][key] = _quantile(arrays[key],nonground)
    opt = gates['optical_available']
    z = arrays['optical__relative_intensity_z']
    median = arrays['optical__local_intensity_median']
    uniform_low = nonground & opt & (arrays['intensity'] <= 3) & (median <= 3) & (np.abs(z) <= .1)
    dense_continuous = nonground & gates['scan_available'] & gates['spatial_available'] & (arrays['geometry__scan_surface_score'] >= .8) & (arrays['geometry__spatial_neighbor_count'] >= 12)
    report['mechanism_probes'] = {
     'uniform_low_I_le3_local_median_le3_absz_le0p1':int(uniform_low.sum()),
     'uniform_low_optical_fail':int((uniform_low & ~gates['optical_pass']).sum()),
     'dense_continuous':int(dense_continuous.sum()),
     'dense_continuous_counts':{name:int(np.count_nonzero(dense_continuous & (arrays['labels']==v))) for name,v in LABELS.items()},
     'E_scan_ge0p9_spatial_below_required':count((arrays['labels']==1) & (arrays['geometry__scan_surface_score']>=.9) & ~gates['solid_support']),
     'E_linearity_dominates_planarity':count((arrays['labels']==1) & (arrays['geometry__linearity']>=arrays['geometry__planarity'])),
     'E_planarity_dominates_linearity':count((arrays['labels']==1) & (arrays['geometry__planarity']>arrays['geometry__linearity']))}
    return report


def frame_report(arrays, config, *, representative_limit=3):
    gates = reconstruct_gates(arrays,config)
    check = check_reconstruction(arrays,gates)
    if not check['exact_match']:
        raise ValueError(f'Frozen decision reconstruction mismatch: {check}')
    cfs = counterfactuals(arrays,gates,config)
    xyz = arrays['xyz']; n = len(xyz)
    scopes = {'full_frame':np.ones(n,bool)}
    for name,b in ROI_CANDIDATES.items():
        scopes[name] = (gates['valid'] & (xyz[:,0]>=b[0]) & (xyz[:,0]<=b[1]) &
                       (xyz[:,1]>=b[2]) & (xyz[:,1]<=b[3]) & (xyz[:,2]>=b[4]) & (xyz[:,2]<=b[5]))
    r = np.linalg.norm(xyz,axis=1)
    h = arrays['ground__ground_height']
    grouped = {}
    for scope_name,scope in scopes.items():
        groups = {'all':statistics(arrays,gates,cfs,scope)}
        for low,high in [(0,5),(5,10),(10,20),(20,40),(40,np.inf)]:
            groups[f'range_{low}_{high}m'] = statistics(arrays,gates,cfs,scope & (r>=low) & (r<high))
        for low,high in [(-np.inf,0),(0,.035),(.035,.4),(.4,.45),(.45,1),(1,np.inf)]:
            groups[f'height_{low}_{high}m'] = statistics(arrays,gates,cfs,scope & (h>=low) & (h<high))
        groups['height_unavailable'] = statistics(arrays,gates,cfs,scope & ~np.isfinite(h))
        for name,value in LABELS.items():groups['final_'+name] = statistics(arrays,gates,cfs,scope & (arrays['labels']==value))
        grouped[scope_name] = groups
    selectors = {
     'A_candidates':gates['aerosol'],
     'uniform_low_optical_fail':gates['valid'] & ~gates['ground'] & gates['optical_available'] &
       (arrays['intensity']<=3) & (arrays['optical__local_intensity_median']<=3) &
       (np.abs(arrays['optical__relative_intensity_z'])<=.1) & ~gates['optical_pass'],
     'only_optical_fails_all_available':gates['valid'] & ~gates['ground'] & gates['all_available'] & ~gates['optical_pass'] & gates['scan_pass'] & gates['spatial_pass'],
     'only_scan_fails_all_available':gates['valid'] & ~gates['ground'] & gates['all_available'] & gates['optical_pass'] & ~gates['scan_pass'] & gates['spatial_pass'],
     'only_spatial_fails_all_available':gates['valid'] & ~gates['ground'] & gates['all_available'] & gates['optical_pass'] & gates['scan_pass'] & ~gates['spatial_pass'],
     'joint_pass_protected':gates['triple_pass'] & gates['protect'] & ~gates['ground'],
     'joint_pass_no_ground_reference':gates['triple_pass'] & ~gates['ground_available'] & ~gates['ground'],
    }
    representatives = {}
    for scope_name,scope in scopes.items():
        representatives[scope_name] = {}
        for name,selector in selectors.items():
            indices = np.flatnonzero(selector & scope)[:representative_limit]
            representatives[scope_name][name] = [
             {'raw_slot_id':int(arrays['raw_slot_id'][i]), 'xyz':xyz[i].tolist(),
              'label':int(arrays['labels'][i]), 'intensity':_finite_float(arrays['intensity'][i]),
              'ground_height':_finite_float(h[i]), 'optical_z':_finite_float(arrays['optical__relative_intensity_z'][i]),
              'scan_surface':_finite_float(arrays['geometry__scan_surface_score'][i]),
              'spatial_surface':_finite_float(arrays['geometry__spatial_surface_score'][i]),
              'spatial_diffuse':_finite_float(arrays['geometry__spatial_diffuse_score'][i]),
              'availability_OSP':format(int(gates['availability_pattern'][i]),'03b'),
              'threshold_OSP':format(int(gates['threshold_pattern'][i]),'03b'),
              'protection_NLE':format(int(gates['protection_pattern'][i]),'03b'),
              'reason_code':int(arrays['reason_code'][i]), 'semantic_truth':'UNKNOWN'} for i in indices]
    report = {'version':VERSION,'diagnostic_only_no_deletion':True,'array_count':len(arrays),
              'reconstruction':check,'grouped':grouped,'representatives':representatives,
              'roi_scope':'fixed coordinate candidates from middle_seq245847; no object tracking or GT',
              'roi_bounds':ROI_CANDIDATES,
              'pattern_bit_order':{'availability':'optical,scan,spatial', 'threshold':'optical,scan,spatial',
                                   'protection':'near,low,edge'}}
    return report,gates,cfs


def _finite_float(x):
    return float(x) if np.isfinite(x) else None
