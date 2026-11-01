#!/usr/bin/env python3
"""Manifest/seq -> exact-slot ROI evidence and optional B/C behavior difference.

Frozen V1B code is imported read-only, with bytecode disabled and all caches
redirected to v1c. Human observations never assign an entire ROI a truth label.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from datetime import datetime,timezone

sys.dont_write_bytecode=True
V1C=Path(__file__).resolve().parents[1];BASE=V1C.parent
os.environ['MPLCONFIGDIR']=str(V1C/'.cache/matplotlib')
os.environ['PYTHONDONTWRITEBYTECODE']='1'
sys.path.insert(0,str(BASE))
import numpy as np
from opdf.visualization import load_result

_spec=importlib.util.spec_from_file_location('frozen_v1b_review_roi',BASE/'scripts/review_roi.py')
_review=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_review)

OBSERVATIONS={
 'suspected_entity_removed':'疑似实体误删',
 'suspected_aerosol_retained':'疑似颗粒漏滤',
 'entity_evidence_conflict':'实体候选冲突',
 'ground_misclassification':'地面误判',
 'unable_to_confirm':'无法确认',
}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path,obj):
    from opdf.pipeline import json_safe
    Path(path).write_text(json.dumps(json_safe(obj),ensure_ascii=False,indent=2,allow_nan=False))


def locate_result(manifest_path,seq,result_dir):
    manifest=json.loads(Path(manifest_path).read_text())
    rows=[row for row in manifest.get('frames',[]) if row.get('seq')==seq]
    if len(rows)!=1:raise ValueError('seq must identify exactly one source frame in manifest')
    entry=rows[0];directory=Path(result_dir)
    candidates=list(directory.glob(f'*seq{seq}.npz'))
    if len(candidates)!=1:raise ValueError(f'Expected one exact result NPZ for seq {seq}; found {candidates}')
    path=candidates[0].resolve();side=json.loads(path.with_suffix('.json').read_text())
    meta=side.get('metadata',side)
    if meta.get('raw_message_sha256')!=entry.get('sha256'):
        raise ValueError('Result raw message SHA differs from manifest')
    for name in ('header_stamp_ns','record_stamp_ns'):
        if meta.get(name)!=entry.get(name):raise ValueError(f'Result {name} differs from manifest')
    if meta.get('seq',seq)!=seq:raise ValueError('Result sequence differs from request')
    return path,entry,side


def compare_arrays(b,c,selection):
    """Require the exact original raw-slot domain and measurement coordinates."""
    if not np.array_equal(b['raw_slot_id'],c['raw_slot_id']):
        raise ValueError('B/C raw-slot domain/order mismatch; no nearest-neighbor substitution')
    for k in ('xyz','intensity','valid_xyz_mask'):
        if b[k].shape!=c[k].shape or not np.array_equal(b[k],c[k],equal_nan=True):
            raise ValueError(f'B/C source measurement mismatch for {k}')
    selected=np.asarray(selection,dtype=int)
    finite=np.isfinite(b['xyz'][selected]).all(axis=1)&b['valid_xyz_mask'][selected]
    result=dict(exact_selected_count=len(selected),valid_selected_count=int(finite.sum()),
                selected_invalid_count=int((~finite).sum()),behavior_not_accuracy=True)
    for name,arrays in (('B',b),('C',c)):
        result[name+'_candidate_counts']={label:int((arrays['labels'][selected][finite]==value).sum())
                                        for value,label in ((1,'E'),(2,'A'),(3,'U'),(4,'G'))}
    changed=b['labels'][selected]!=c['labels'][selected]
    result['changed_label_count']=int((changed&finite).sum())
    result['transitions']={}
    names={0:'INVALID',1:'E',2:'A',3:'U',4:'G'}
    for old,new in zip(b['labels'][selected][finite],c['labels'][selected][finite]):
        key=names[int(old)]+'->'+names[int(new)]
        result['transitions'][key]=result['transitions'].get(key,0)+1
    result['changed_reason_count']=int((b['reason_code'][selected]!=c['reason_code'][selected]).sum())
    # An additive suspect mask is evidence for review, never an A/delete action.
    mask_keys=[k for k,v in c.items() if 'suspect' in k.lower() and np.asarray(v).shape==(len(c['xyz']),) and np.asarray(v).dtype.kind=='b']
    result['C_additive_suspect_counts']={k:int(np.asarray(c[k])[selected][finite].sum()) for k in mask_keys}
    return result


def export_comparison(manifest_path,seq,b_results,output,*,c_results=None,roi=None,view=None,
                      blind=False,reviewer=None,confidence=None,observation=None,note=None,
                      point_notes=None,max_points=12000,selection_provenance=None):
    out=Path(output).resolve()
    if not out.is_relative_to(V1C) or out.exists():raise ValueError('Output must be a new directory under v1c')
    if observation is not None and (observation not in OBSERVATIONS or not reviewer):
        raise ValueError('Human observation requires an actual supplied reviewer')
    if confidence is not None and (not reviewer or not np.isfinite(confidence) or not 0<=confidence<=1):
        raise ValueError('Confidence requires actual reviewer input and must lie in [0,1]')
    bp,entry,bside=locate_result(manifest_path,seq,b_results);b=load_result(bp)
    selected=_review.exact_selection(b,roi)
    cp=c=None
    if c_results:
        cp,centry,cside=locate_result(manifest_path,seq,c_results);c=load_result(cp)
        comparison=compare_arrays(b,c,selected)
    else:comparison=dict(status='C_NOT_SUPPLIED',performance_computed=False)
    # Export source checks before output directory exists. Never overwrite cases.
    out.mkdir(parents=True)
    bcase=_review.export_review(bp,out/'B',roi=roi,view=view,blind=blind,max_points=max_points)
    if cp:
        _review.export_review(cp,out/'C',roi=roi,view=bcase['camera'],blind=blind,max_points=max_points)
    if blind:
        comparison=dict(status='BLIND_COMPARISON_DEFERRED',exact_selected_count=len(selected),
                        source_domains_validated=bool(cp),performance_computed=False)
    else:
        if cp:
            np.savez_compressed(out/'exact_slot_changes.npz',raw_slot_id=b['raw_slot_id'][selected],
                 B_labels=b['labels'][selected],C_labels=c['labels'][selected],
                 B_reason_code=b['reason_code'][selected],C_reason_code=c['reason_code'][selected],
                 changed_label=b['labels'][selected]!=c['labels'][selected])
        table=['raw_slot_id,x,y,z,intensity,B_label,B_reason_code,C_label,C_reason_code']
        for j in selected:
            xyz=b['xyz'][j]
            table.append(','.join(map(str,[int(b['raw_slot_id'][j]),*xyz,float(b['intensity'][j]),
                         int(b['labels'][j]),int(b['reason_code'][j]),int(c['labels'][j]) if cp else '',int(c['reason_code'][j]) if cp else ''])))
        (out/'diagnostic_slots.csv').write_text('\n'.join(table)+'\n')
    write_json(out/'comparison.json',comparison)
    identity=dict(version=1,created_utc=datetime.now(timezone.utc).isoformat(),seq=seq,
        manifest=str(Path(manifest_path).resolve()),manifest_sha256=sha(manifest_path),source_entry=entry,
        B_npz=str(bp),B_npz_sha256=sha(bp),C_npz=str(cp) if cp else None,C_npz_sha256=sha(cp) if cp else None,
        roi=roi,camera=bcase['camera'],blind=blind,selection_provenance=selection_provenance,
        exact_selected_count=len(selected),raw_slot_list='B/raw_slot_ids.npy',
        evidence_status='CANDIDATE_REGION_NOT_MATERIAL_GROUND_TRUTH')
    write_json(out/'comparison_case.json',identity)
    write_json(out/'human_observation.json',dict(reviewer_id=reviewer,confidence=confidence,
        observation=observation,observation_display=OBSERVATIONS.get(observation),note=note,
        status='USER_SUPPLIED_SUSPECTED_OBSERVATION' if observation else 'PENDING_HUMAN_REVIEW',
        independent_gt=False,whole_roi_semantic_label=None,
        warning='Observation category is not a pointwise or whole-region material truth label'))
    if point_notes:
        supplied=json.loads(Path(point_notes).read_text())
        if not isinstance(supplied,list):raise ValueError('Point notes must be a list of actual user-supplied records')
        selected_valid={int(b['raw_slot_id'][j]) for j in selected if b['valid_xyz_mask'][j] and np.isfinite(b['xyz'][j]).all()}
        seen=set()
        for row in supplied:
            slot=row.get('raw_slot_id')
            if isinstance(slot,bool) or not isinstance(slot,int) or slot not in selected_valid or slot in seen:
                raise ValueError('Point note must identify unique valid selected raw slot')
            if not row.get('reviewer_id') or not row.get('evidence') or row.get('label') not in ('E','A','U','G'):
                raise ValueError('Point note needs actual reviewer, evidence and E/A/U/G label')
            seen.add(slot)
        write_json(out/'user_supplied_point_notes.json',dict(records=supplied,source_json_sha256=sha(point_notes),
                   status='RECORDED_NOT_ADJUDICATED_REFERENCE',unannotated_selected_slots_remain_unknown=True))
    return identity


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,default=V1C/'samples/continuous30/manifest.json')
    p.add_argument('--seq',type=int,required=True);p.add_argument('--b-results',type=Path,default=V1C/'outputs/v1b_continuous30/frames')
    p.add_argument('--c-results',type=Path);p.add_argument('--output',required=True)
    p.add_argument('--bbox',nargs=6,type=float);p.add_argument('--slots',nargs='+',type=int)
    p.add_argument('--slots-file',help='JSON array of exact source raw slot IDs')
    p.add_argument('--view');p.add_argument('--blind',action='store_true');p.add_argument('--max-points',type=int,default=12000)
    p.add_argument('--from-case',type=Path,help='Reuse prior exact ROI/view only; never import its semantic truth')
    p.add_argument('--reviewer');p.add_argument('--confidence',type=float)
    p.add_argument('--observation',choices=list(OBSERVATIONS));p.add_argument('--note');p.add_argument('--point-notes')
    a=p.parse_args();roi={};view=a.view;provenance=None
    if a.from_case:
        prior=json.loads(a.from_case.read_text());roi=prior.get('roi',{});view=view or prior.get('camera')
        provenance=dict(prior_case=str(a.from_case.resolve()),sha256=sha(a.from_case),
                        reused='ROI and camera only; labels/material semantics NOT imported')
    if a.bbox is not None:roi['bbox']=a.bbox
    if a.slots_file:roi['raw_slot_ids']=json.loads(Path(a.slots_file).read_text())
    elif a.slots is not None:roi['raw_slot_ids']=a.slots
    result=export_comparison(a.manifest,a.seq,a.b_results,a.output,c_results=a.c_results,roi=roi,view=view,
        blind=a.blind,reviewer=a.reviewer,confidence=a.confidence,observation=a.observation,note=a.note,
        point_notes=a.point_notes,max_points=a.max_points,selection_provenance=provenance)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
