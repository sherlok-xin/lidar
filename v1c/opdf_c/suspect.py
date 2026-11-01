"""Additive review evidence; never changes E/A/U/G or authorizes deletion."""
import numpy as np
from .gate_diagnostics import reconstruct_gates

VERSION='OPDF-V1-C-diagnostic/1.0'
DEFAULT={'uniform_low_enabled':True,'uniform_intensity_max':3.,'uniform_local_median_max':3.,
         'uniform_abs_relative_z_max':.1,'required_evidence_categories':2}
REASONS={'RELATIVE_WEAK':1,'UNIFORM_LOW_NUMERIC_PROBE':2,'SCAN_DISCONTINUOUS':4,
         'SPATIAL_DIFFUSE':8,'LOW_PROTECTED':16,'NEAR_PROTECTED':32,'EDGE_PROTECTED':64,
         'ENTITY_OPTICAL_CONFLICT':128,'SUSPECT_REVIEW_ONLY':256}

def compute(arrays,base_config,config):
    cfg={**DEFAULT,**config};g=reconstruct_gates(arrays,base_config)
    if cfg['required_evidence_categories']!=2:raise ValueError('This version fixes two evidence categories; do not silently retune')
    valid=g['valid'];nonground=valid&~g['ground'];n=len(valid)
    numeric=(nonground & g['optical_available'] & np.isfinite(arrays['intensity']) &
             (arrays['intensity']<=cfg['uniform_intensity_max']) &
             (arrays['optical__local_intensity_median']<=cfg['uniform_local_median_max']) &
             (np.abs(arrays['optical__relative_intensity_z'])<=cfg['uniform_abs_relative_z_max']))
    # A numeric optical probe is only a review cue. It cannot create a suspect
    # without an independently available geometric cue, and never creates A.
    optical=g['optical_pass'] | (numeric if cfg['uniform_low_enabled'] else False)
    categories=optical.astype(np.uint8)+g['scan_pass'].astype(np.uint8)+g['spatial_pass'].astype(np.uint8)
    availability=g['optical_available'].astype(np.uint8)+g['scan_available'].astype(np.uint8)+g['spatial_available'].astype(np.uint8)
    available=nonground&(availability>=2)
    suspect=available&(categories>=2)&(arrays['labels']!=2)
    conflict=(arrays['labels']==1)&optical
    protected=suspect&g['protect']
    reasons=np.zeros(n,np.uint16)
    for key,mask in [('RELATIVE_WEAK',g['optical_pass']),('UNIFORM_LOW_NUMERIC_PROBE',numeric&bool(cfg['uniform_low_enabled'])),
                     ('SCAN_DISCONTINUOUS',g['scan_pass']),('SPATIAL_DIFFUSE',g['spatial_pass']),
                     ('LOW_PROTECTED',g['low']),('NEAR_PROTECTED',g['near']),('EDGE_PROTECTED',g['edge']),
                     ('ENTITY_OPTICAL_CONFLICT',conflict),('SUSPECT_REVIEW_ONLY',suspect)]:
        reasons[nonground&mask]|=REASONS[key]
    return {'aerosol_suspect_mask':suspect,'aerosol_suspect_available_mask':available,
            'suspect_uniform_low_mask':numeric&bool(cfg['uniform_low_enabled']),
            'entity_optical_conflict_mask':conflict,'suspect_protected_mask':protected,
            'suspect_evidence_count':categories,'suspect_reason_code':reasons}
