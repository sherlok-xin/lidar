#!/usr/bin/env python3
"""V1-D source-bound RAW neighbor review and D1/D2 exact-slot comparison.

No automatic human observation, material label, model training or new bag IO.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from datetime import datetime,timezone
sys.dont_write_bytecode=True
DROOT=Path(__file__).resolve().parents[1];BASE=DROOT.parent
os.environ['MPLCONFIGDIR']=str(DROOT/'.cache/matplotlib')
os.environ['TMPDIR']=str(DROOT/'.cache/tmp');os.environ['PYTHONDONTWRITEBYTECODE']='1'
Path(os.environ['TMPDIR']).mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(DROOT));sys.path.insert(0,str(BASE))
import numpy as np
from opdf.pipeline import json_safe
from opdf_d.visualization import load_result,_old,render_raw_context,render_d1_views


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_json(p,obj):Path(p).write_text(json.dumps(json_safe(obj),ensure_ascii=False,indent=2,allow_nan=False))


def locate(manifest_path,seq,directory):
    manifest=json.loads(Path(manifest_path).read_text());entries=[r for r in manifest['frames'] if r['seq']==seq]
    if len(entries)!=1:raise ValueError('seq must identify one source message in manifest')
    candidates=list(Path(directory).glob(f'*seq{seq}.npz'))
    if len(candidates)!=1:raise ValueError(f'Expected one NPZ for {seq}: {candidates}')
    p=candidates[0].resolve();side=json.loads(p.with_suffix('.json').read_text());m=side.get('metadata',side)
    entry=entries[0]
    for name in ('header_stamp_ns','record_stamp_ns'):
        if m.get(name)!=entry.get(name):raise ValueError(f'{seq} {name} identity mismatch')
    if not m.get('raw_message_sha256') or m['raw_message_sha256']!=entry['sha256']:
        raise ValueError('Source message SHA mismatch')
    return p,entry,side


def domain(b,d):
    for name in ('raw_slot_id','xyz','intensity','valid_xyz_mask'):
        if b[name].shape!=d[name].shape or b[name].dtype!=d[name].dtype or np.ascontiguousarray(b[name]).tobytes()!=np.ascontiguousarray(d[name]).tobytes():
            raise ValueError(f'Exact original measurement domain differs: {name}')


def new_directory(path):
    p=Path(path).resolve()
    if not p.is_relative_to(DROOT) or p.exists():raise ValueError('Use a new output directory under v1d')
    p.mkdir(parents=True);return p


def export_raw_case(manifest,frames,seq,output,*,roi,view=None,neighbors=None,
                    selection_reason=None,selection_source=None,max_points=5000):
    seqs=list(neighbors or [seq-1,seq,seq+1])
    if seq not in seqs:raise ValueError('Context must include focal seq')
    sources=[locate(manifest,s,frames) for s in seqs]
    out=new_directory(output);archive=out/'algorithm_evidence_unblinded';archive.mkdir()
    rawdir=out/'blind_raw';rawdir.mkdir()
    source_rows=[]
    for s,(p,entry,side) in zip(seqs,sources):
        a=load_result(p);idx=_old.exact_selection(a,roi)
        # All source features are archived separately from the blind entry.
        aligned={k:v[idx] for k,v in a.items() if np.asarray(v).ndim and len(v)==len(a['xyz'])}
        np.savez_compressed(archive/f'seq{s}_all_features.npz',**aligned)
        raw={k:a[k][idx] for k in ('xyz','intensity','valid_xyz_mask','raw_slot_id')}
        np.savez_compressed(rawdir/f'seq{s}_raw.npz',**raw)
        source_rows.append(dict(seq=s,source_npz=str(p),source_npz_sha256=sha(p),source_entry=entry,
           source_sidecar=str(p.with_suffix('.json')),source_sidecar_sha256=sha(p.with_suffix('.json')),
           exact_roi_count=len(idx),feature_count=len(aligned),
           raw_slot_sha256=hashlib.sha256(a['raw_slot_id'][idx].astype('<u8').tobytes()).hexdigest(),
           raw_slot_path=str((rawdir/f'seq{s}_raw.npz').relative_to(out))))
    shown=render_raw_context([p for p,_,_ in sources],output_png=rawdir/'raw_neighbors.png',
                    view=view,max_points=max_points,roi=roi)
    case=dict(version=1,focal_seq=seq,context_sequences=seqs,
       manifest=str(Path(manifest).resolve()),manifest_sha256=sha(manifest),roi=roi,camera=shown['camera'],
       source_frames=source_rows,selection_owner='ASSISTANT_GEOMETRIC_CANDIDATE_SELECTION',
       selection_reason=selection_reason,selection_source=selection_source,
       material_identity='UNKNOWN',ground_truth=False,independent_instance_identity=False,
       created_utc=datetime.now(timezone.utc).isoformat(),blind_entry='blind_raw/raw_neighbors.png',
       warning='All-feature archive is unblinded algorithm evidence; do not open before independent RAW review')
    write_json(out/'case.json',case)
    write_json(out/'human_review.json',dict(reviewer_id=None,confidence=None,observation=None,
         point_annotations=None,instance_annotations=None,status='PENDING_HUMAN_REVIEW',
         material_identity='UNKNOWN',whole_roi_semantic_label=None,independent_reference=False))
    write_json(out/'view.json',shown['camera']);return case


def five_cases(manifest,frames,output,max_points=5000):
    out=new_directory(output);rows=[]
    oldroot=BASE/'v1c/outputs/review_stage2'
    definitions=[]
    for name in ('vehicle_structure_candidate','near_ground_rough_vegetation_candidate','aerosol_surface_ambiguity'):
        prior=oldroot/name/'comparison_case.json';old=json.loads(prior.read_text())
        definitions.append((name,old['roi'],old['camera'],
           'Reused prior geometric selection; material/vehicle/vegetation/aerosol identity unverified',
           dict(prior_case=str(prior.resolve()),sha256=sha(prior))))
    definitions.extend([
       ('vehicle_body_edge_candidate',{'bbox':[4,7,-2,2,-.6,1.6]},
        {'target':[6,1,0],'distance':6,'azimuth_deg':-65,'elevation_deg':20},
        'RAW bounded patch adjoining prior structure region; edge/body is a review hypothesis, not an identified vehicle',None),
       ('possible_low_obstacle_unknown',{'bbox':[7,9,5,7,-1.5,-.9]},
        {'target':[8,6,-1.2],'distance':4,'azimuth_deg':-65,'elevation_deg':28},
        'RAW low-elevation patch with observed vertical spread; hard/soft/ground/particle identity UNKNOWN; not called a stone',None)])
    for name,roi,view,reason,provenance in definitions:
        c=export_raw_case(manifest,frames,245847,out/name,roi=roi,view=view,
            selection_reason=reason,selection_source=provenance,max_points=max_points)
        rows.append(dict(case=name,path=str((out/name/'case.json').resolve()),focal_seq=c['focal_seq'],
                        context=c['context_sequences'],exact_counts={str(r['seq']):r['exact_roi_count'] for r in c['source_frames']},
                        material_identity='UNKNOWN',human_review='PENDING_HUMAN_REVIEW'))
    write_json(out/'catalog.json',rows);return rows


def render_cases_d1(cases,d1_dir,output,max_points=5000):
    catalog=json.loads((Path(cases)/'catalog.json').read_text());out=new_directory(output);rows=[]
    for row in catalog:
        c=json.loads(Path(row['path']).read_text());p,entry,_=locate(c['manifest'],c['focal_seq'],d1_dir)
        baseline=load_result(next(r['source_npz'] for r in c['source_frames'] if r['seq']==c['focal_seq']))
        domain(baseline,load_result(p))
        sub=out/row['case'];sub.mkdir()
        rendered=render_d1_views(p,output_png=sub/'d1_sets.png',roi=c['roi'],view=c['camera'],max_points=max_points)
        rows.append(dict(case=row['case'],**{k:v for k,v in rendered.items() if k!='display_raw_slot_ids'}))
    write_json(out/'d1_roi_summary.json',rows);return rows


def summarize_cases_d1(cases,d1_dir,output):
    """Full exact ROI features and B-label overlaps, not ground-truth errors."""
    catalog=json.loads((Path(cases)/'catalog.json').read_text());out=new_directory(output);rows=[]
    for row in catalog:
        case=json.loads(Path(row['path']).read_text());seq=case['focal_seq']
        source=next(r for r in case['source_frames'] if r['seq']==seq);bp=Path(source['source_npz'])
        if sha(bp)!=source['source_npz_sha256']:raise ValueError('Frozen ROI baseline NPZ changed')
        dp,entry,side=locate(case['manifest'],seq,d1_dir);b=load_result(bp);d=load_result(dp);domain(b,d)
        preserved=all(k in d and np.array_equal(v,d[k],equal_nan=True) for k,v in b.items())
        if not preserved:raise ValueError('D1 changed an original B array')
        idx=_old.exact_selection(b,case['roi']);sub=out/row['case'];sub.mkdir()
        np.savez_compressed(sub/'exact_d1_features.npz',**{k:v[idx] for k,v in d.items() if np.asarray(v).ndim and len(v)==len(d['xyz'])})
        sets={name:np.asarray(d['d1__'+key],bool) for name,key in {
             'core':'ground_core_mask','clutter':'low_clutter_mask','strict':'nonground_strict_mask',
             'display':'nonground_display_mask','hard_protect':'hard_structure_protect_mask',
             'ground_available':'ground_available','risk_unknown':'risk_unknown_mask'}.items()}
        summary=dict(case=row['case'],seq=seq,exact_roi_count=len(idx),source_message_sha256=entry['sha256'],
          B_npz_sha256=sha(bp),D1_npz_sha256=sha(dp),D1_sidecar_sha256=sha(dp.with_suffix('.json')),
          B_original_array_count=len(b),all_B_arrays_preserved=preserved,labels_unchanged=bool(np.array_equal(b['labels'],d['labels'])),
          material_identity='UNKNOWN',behavior_not_accuracy=True,performance_computed=False,
          **{name+'_count':int(mask[idx].sum()) for name,mask in sets.items()})
        for value,label in ((1,'E'),(2,'A'),(3,'U'),(4,'G')):
            original=b['labels']==value;summary['B_'+label+'_count']=int(original[idx].sum())
            for name in ('core','clutter','strict','display'):
                summary[name+'_from_B_'+label]=int((sets[name][idx]&original[idx]).sum())
        for feature in ('ground__low_object_mask','ground__near_ground_mask','geometry__edge_protect_mask'):
            if feature in b:
                summary['core_overlap_'+feature]=int((sets['core'][idx]&np.asarray(b[feature][idx],bool)).sum())
                summary['clutter_overlap_'+feature]=int((sets['clutter'][idx]&np.asarray(b[feature][idx],bool)).sum())
        local=np.asarray(d['d1__local_height'][idx],float);known=np.isfinite(local)&sets['ground_available'][idx]
        summary['local_height_unavailable_count']=int((~known).sum())
        summary['local_height_q10_q50_q90_m']=np.quantile(local[known],[.1,.5,.9]).tolist() if known.any() else None
        with (sub/'exact_sets_and_b_labels.csv').open('w',newline='') as f:
            writer=csv.writer(f);writer.writerow(['raw_slot_id','x','y','z','intensity','B_label','B_reason',
                'D1_reason','D1_local_height_m','D1_ground_available','GroundCore','LowClutter','Strict','Display','HardProtect'])
            for i in idx:
                writer.writerow([int(b['raw_slot_id'][i]),*b['xyz'][i],float(b['intensity'][i]),int(b['labels'][i]),
                    int(b['reason_code'][i]),int(d['d1__reason_code'][i]),float(d['d1__local_height'][i]),
                    *[int(sets[k][i]) for k in ('ground_available','core','clutter','strict','display','hard_protect')]])
        write_json(sub/'behavior.json',summary);rows.append(summary)
    write_json(out/'d1_b_roi_behavior.json',rows)
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with (out/'d1_b_roi_behavior.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
    return rows


def compare_case_d2(case_path,d2_dir,output,max_points=5000):
    c=json.loads(Path(case_path).read_text());seq=c['focal_seq']
    original=next(r for r in c['source_frames']if r['seq']==seq);bp=Path(original['source_npz'])
    if sha(bp)!=original['source_npz_sha256']:raise ValueError('Source case baseline NPZ changed')
    if sha(c['manifest'])!=c['manifest_sha256']:raise ValueError('Source case manifest changed')
    dp,entry,side=locate(c['manifest'],seq,d2_dir);b=load_result(bp);d=load_result(dp);domain(b,d)
    baseline_fields=('labels','score_e','score_a','available_e','available_a','reason_code',
                     'retain_solid_mask','retain_with_ground_mask','aerosol_candidate_mask')
    for key in baseline_fields:
        if key not in b or key not in d:continue
        changed=not np.array_equal(b[key],d[key],equal_nan=True)
        saved='b__'+key
        if changed and saved not in d:raise ValueError(f'D2 changed {key} without preserving {saved}')
        if saved in d and not np.array_equal(b[key],d[saved],equal_nan=True):
            raise ValueError(f'D2 {saved} does not match frozen B input')
    idx=_old.exact_selection(b,c['roi']);out=new_directory(output)
    _old.export_review(bp,out/'B',roi=c['roi'],view=c['camera'],max_points=max_points)
    _old.export_review(dp,out/'D',roi=c['roi'],view=c['camera'],max_points=max_points)
    # Old renderer is measurement-only reusable infrastructure. Its diagnostics
    # namespaces/config hash are inherited B metadata and must not decode new D2 decisions.
    if 'd2_config_sha256' in side:
        adapt_d2_review_metadata(out/'D',side)
    flags=dict(B_E_to_D_A=(b['labels']==1)&(d['labels']==2),B_U_to_D_A=(b['labels']==3)&(d['labels']==2),
               B_E_to_D_U=(b['labels']==1)&(d['labels']==3),B_A_to_D_nonA=(b['labels']==2)&(d['labels']!=2),
               labels_changed=b['labels']!=d['labels'])
    np.savez_compressed(out/'exact_transitions.npz',raw_slot_id=b['raw_slot_id'][idx],B_labels=b['labels'][idx],D_labels=d['labels'][idx],
                       **{k:v[idx] for k,v in flags.items()})
    csv=['raw_slot_id,B_label,D_label,B_E_to_D_A,B_U_to_D_A,B_E_to_D_U,B_A_to_D_nonA']
    for i in idx:
        if any(v[i] for v in flags.values()):
            csv.append(','.join(map(str,[int(b['raw_slot_id'][i]),int(b['labels'][i]),int(d['labels'][i]),
                         *[int(flags[k][i]) for k in ('B_E_to_D_A','B_U_to_D_A','B_E_to_D_U','B_A_to_D_nonA')]])))
    (out/'candidate_risk_transitions.csv').write_text('\n'.join(csv)+'\n')
    summary=dict(source_case=str(Path(case_path).resolve()),source_seq=seq,source_message_sha256=entry['sha256'],
       B_npz_sha256=sha(bp),D_npz_sha256=sha(dp),D_sidecar_sha256=sha(dp.with_suffix('.json')),
       D2_config_sha256=side.get('d2_config_sha256'),base_B_config_sha256=side.get('config_sha256'),
       D2_reason_bits=side.get('d2_fusion_diagnostics',{}).get('reason_bits'),roi=c['roi'],camera=c['camera'],
       full_frame_behavior={k:int(v.sum()) for k,v in flags.items()},roi_behavior={k:int(v[idx].sum()) for k,v in flags.items()},
       B_G_count=int((b['labels']==4).sum()),D_label_G_count=int((d['labels']==4).sum()),
       B_G_preserved_exactly=bool(np.array_equal(b['labels']==4,d['labels']==4)),
       D1_GroundCore_count=int(d['d1__ground_core_mask'].sum()) if 'd1__ground_core_mask' in d else None,
       ground_semantics='D1 GroundCore is not D2 labels G; D2 may intentionally preserve frozen B G',
       interpretation='Candidate-risk transitions only, not independently confirmed new entity loss or aerosol performance',
       human_review='PENDING_HUMAN_REVIEW',performance_computed=False)
    write_json(out/'comparison.json',summary);return summary


def adapt_d2_review_metadata(output,side):
    output=Path(output);diag=side.get('d2_fusion_diagnostics',{})
    bits=diag.get('reason_bits')
    if not bits or not side.get('d2_config_sha256'):raise ValueError('Actual D2 reason/config definition missing')
    modules=side.get('diagnostics',{}).get('modules',{})
    definitions={'standard_reason_code':{'namespace':'D2 fusion decision','reason_bits':bits,
        'version':diag.get('version'),'ablation':diag.get('ablation')},
        'b__reason_code':{'namespace':'frozen original B fusion decision','source_modules':modules},
        'original_feature_reason_namespaces':modules,
        'warning':'B/D1 inherited diagnostics do NOT decode standard D2 reason_code; no material truth'}
    write_json(output/'reason_definitions.json',definitions)
    cp=output/'case.json';case=json.loads(cp.read_text())
    case.update(heuristic_config_sha256=side['d2_config_sha256'],base_B_config_sha256=side.get('config_sha256'),
        decision_namespace='D2 fusion decision; see reason_definitions.json',
        original_diagnostics_namespace='B/D1 inherited feature evidence only',
        D2_ablation=diag.get('ablation'),D2_method=side.get('method'),
        regression_policy='Use D2 frozen source/config pipeline; original B regress_case is not a D2 regression')
    write_json(cp,case)
    html=output/'review.html'
    if html.exists():
        content=html.read_text();content=content.replace('<body>','<body><p>Standard reason_code = D2 fusion decision; '
            'b__reason_code = frozen B. <a href="reason_definitions.json">Exact reason namespaces</a>. '
            'All labels are heuristic candidates; no independent GT.</p>',1);html.write_text(content)


def summarize_run_d2(manifest_path,b_frames,d2_dir,output):
    """Full original-slot denominators and exact changes; references all feature arrays.

    Refuses incomplete inputs rather than silently selecting the frames that worked.
    The all-feature source NPZ remains authoritative, and its hash is recorded per row.
    """
    from opdf_d.ros_layers import DECISION_KEYS,equal_bits
    manifest=json.loads(Path(manifest_path).read_text());entries=manifest['frames']
    if not entries or len({e['seq']for e in entries})!=len(entries):raise ValueError('Empty/duplicate manifest')
    paths=[]
    for e in entries:
        for folder in (b_frames,d2_dir):
            p=Path(folder)/(e['key']+'.npz')
            if not p.is_file()or not p.with_suffix('.json').is_file():raise ValueError('Incomplete run '+str(p))
        paths.append((e,Path(b_frames)/(e['key']+'.npz'),Path(d2_dir)/(e['key']+'.npz')))
    out=new_directory(output);rows=[];matrix=np.zeros((5,5),np.int64);configs=set();sources=[]
    header=['seq','raw_slot_id','x','y','z','intensity','B_label','D_label','B_reason_code','D_reason_code',
            'B_score_e','D_score_e','B_available_e','D_available_e','B_score_a','D_score_a','B_available_a','D_available_a',
            'all_features_source_npz','all_features_source_sha256']
    with(out/'candidate_risk_exact_slots.csv').open('w',newline='')as f:
        writer=csv.writer(f);writer.writerow(header)
        for e,bp,dp in paths:
            _,_,side=locate(manifest_path,e['seq'],d2_dir);locate(manifest_path,e['seq'],b_frames)
            b=load_result(bp);d=load_result(dp);domain(b,d)
            for key,value in b.items():
                candidate=d.get('b__'+key,d.get(key))if key in DECISION_KEYS else d.get(key)
                if candidate is None or not equal_bits(value,candidate):raise ValueError('Original B source mismatch '+key)
            valid=b['valid_xyz_mask']&np.isfinite(b['xyz']).all(1);old=b['labels'];new=d['labels']
            if np.any(new[~valid]!=0)or np.any(new[valid]==0):raise ValueError('Decision/valid-domain mismatch')
            if np.any(new>4):raise ValueError('Unknown class code')
            flags={'new_E':valid&(new==1)&(old!=1),'lost_E':valid&(old==1)&(new!=1),
                'new_A':valid&(new==2)&(old!=2),'lost_A':valid&(old==2)&(new!=2),
                'E_to_U':valid&(old==1)&(new==3),'E_to_A':valid&(old==1)&(new==2),
                'U_to_A':valid&(old==3)&(new==2),'changed':valid&(old!=new)}
            local=np.zeros((5,5),np.int64);np.add.at(local,(old,new),1);matrix+=local
            core=np.asarray(d['d1__ground_core_mask'],bool);dh=sha(dp);configs.add(side.get('d2_config_sha256'))
            if None in configs:raise ValueError('D2 config identity missing')
            row=dict(seq=e['seq'],slots=len(old),finite=int(valid.sum()),invalid=int((~valid).sum()),
                B_G_count=int((old==4).sum()),D_label_G_count=int((new==4).sum()),D1_GroundCore_count=int(core.sum()),
                B_G_changed=int(((old==4)!=(new==4)).sum()),
                **{k:int(v.sum())for k,v in flags.items()})
            for code,name in ((1,'E'),(2,'A'),(3,'U'),(4,'G')):
                row['B_'+name]=int((old==code).sum());row['D_'+name]=int((new==code).sum())
            for name,mask in [('range_lt10',np.linalg.norm(b['xyz'],axis=1)<10),
                ('range_10to20',(np.linalg.norm(b['xyz'],axis=1)>=10)&(np.linalg.norm(b['xyz'],axis=1)<20)),
                ('range_ge20',np.linalg.norm(b['xyz'],axis=1)>=20),
                ('raw_z_lt_minus1',b['xyz'][:,2]<-1),('raw_z_minus1to0',(b['xyz'][:,2]>=-1)&(b['xyz'][:,2]<0)),
                ('raw_z_ge0',b['xyz'][:,2]>=0)]:
                use=mask&valid;den=int(use.sum());count=int(((new==2)&use).sum())
                row[name+'_finite']=den;row[name+'_D_A']=count;row[name+'_D_A_fraction']=count/den if den else None
            rows.append(row)
            selected=np.flatnonzero(flags['changed'])
            np.savez_compressed(out/(e['key']+'_exact_changes.npz'),raw_slot_id=b['raw_slot_id'][selected],
                B_labels=old[selected],D_labels=new[selected],**{k:v[selected]for k,v in flags.items()})
            for i in selected:
                writer.writerow([e['seq'],int(b['raw_slot_id'][i]),*b['xyz'][i],b['intensity'][i],int(old[i]),int(new[i]),
                    int(b['reason_code'][i]),int(d['reason_code'][i]),b['score_e'][i],d['score_e'][i],bool(b['available_e'][i]),bool(d['available_e'][i]),
                    b['score_a'][i],d['score_a'][i],bool(b['available_a'][i]),bool(d['available_a'][i]),str(dp.resolve()),dh])
            sources.append({'seq':e['seq'],'source_message_sha256':e['sha256'],'B_npz_sha256':sha(bp),
                'D_npz':str(dp.resolve()),'D_npz_sha256':dh,'D_sidecar_sha256':sha(dp.with_suffix('.json')),
                'all_features_are_source_arrays':True,'D2_reason_bits':side.get('d2_fusion_diagnostics',{}).get('reason_bits')})
    if len(configs)!=1:raise ValueError('Mixed D2 configs cannot be pooled')
    with(out/'per_frame_behavior.csv').open('w',newline='')as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary={'frames':len(rows),'source_manifest_sha256':sha(manifest_path),'d2_config_sha256':next(iter(configs)),
        'counts':{k:sum(r[k]for r in rows)for k in ('slots','finite','invalid','B_G_count','D_label_G_count','D1_GroundCore_count','B_G_changed','new_E','lost_E','new_A','lost_A','E_to_U','E_to_A','U_to_A','changed')},
        'transition_matrix_including_invalid':matrix.tolist(),'source_frames':sources,
        'denominator':'original full raw slots and separately finite original points; no frame drops or display cap',
        'range_definition':'3D norm of raw source xyz; raw_z bins are sensor coordinates, not certified object height',
        'independent_GT':False,'performance_computed':False,'human_review':'PENDING_HUMAN_REVIEW',
        'semantic_warning':'Candidate labels/changes only; original U may contain entities. E->U retained, new A not proven particle; D1 Core independent of D label G'}
    write_json(out/'run_behavior.json',summary);return summary


def import_human_review(case_path,review_path,output):
    """Record actual supplied annotations; structural checks do not certify GT."""
    case=json.loads(Path(case_path).read_text());review=json.loads(Path(review_path).read_text())
    focal=next(r for r in case['source_frames'] if r['seq']==case['focal_seq'])
    if review.get('source_message_sha256')!=focal['source_entry']['sha256']:
        raise ValueError('Human reference source message hash mismatch')
    if not review.get('reviewer_id') or not review.get('evidence'):
        raise ValueError('Actual reviewer and evidence are required')
    confidence=review.get('confidence')
    if confidence is not None and (not isinstance(confidence,(int,float)) or not np.isfinite(confidence) or not 0<=confidence<=1):
        raise ValueError('Supplied confidence must be finite 0..1 or null')
    rawfile=Path(case_path).resolve().parent/focal['raw_slot_path']
    with np.load(rawfile,allow_pickle=False) as raw:
        valid=raw['valid_xyz_mask']&np.isfinite(raw['xyz']).all(1)
        ids={int(v) for v in raw['raw_slot_id'][valid]}
    points=review.get('point_annotations',[]);instances=review.get('instance_annotations',[])
    if not points and not instances:raise ValueError('Empty template is not an annotation submission')
    seen=set()
    for row in points:
        slot=row.get('raw_slot_id')
        if isinstance(slot,bool) or not isinstance(slot,int) or slot not in ids or slot in seen:
            raise ValueError('Point annotation must identify one valid selected original slot')
        if row.get('label') not in ('E','A','U','G'):raise ValueError('Point label must be E/A/U/G')
        seen.add(slot)
    instance_ids=set()
    for row in instances:
        if not row.get('instance_id') or row['instance_id'] in instance_ids or not row.get('evidence'):
            raise ValueError('Instance annotations need unique actual identity/evidence')
        if row.get('presence_status') not in ('observed_support','independently_known_no_return','unknown'):
            raise ValueError('Instance presence must separate support / known no return / unknown')
        if any(isinstance(s,bool) or not isinstance(s,int) or s not in ids for s in row.get('raw_slot_ids',[])):
            raise ValueError('Instance slot is not a valid selected source slot')
        instance_ids.add(row['instance_id'])
    out=new_directory(output)
    result=dict(source_case=str(Path(case_path).resolve()),source_case_sha256=sha(case_path),
        submitted_json_sha256=sha(review_path),submission=review,
        status='USER_SUPPLIED_NOT_INDEPENDENTLY_ADJUDICATED',point_annotation_count=len(points),
        instance_annotation_count=len(instances),unannotated_selected_slots_unknown=True,
        independent_gt_certified=False,performance_computed=False)
    write_json(out/'supplied_human_review.json',result);return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',default=str(BASE/'v1c/samples/continuous30/manifest.json'))
    p.add_argument('--frames',default=str(BASE/'v1c/outputs/v1b_continuous30/frames'))
    p.add_argument('--output',required=True);p.add_argument('--max-points',type=int,default=5000)
    p.add_argument('--init-five',action='store_true');p.add_argument('--render-d1',action='store_true');p.add_argument('--summarize-d1',action='store_true');p.add_argument('--compare-d2',action='store_true');p.add_argument('--summarize-d2',action='store_true')
    p.add_argument('--cases');p.add_argument('--case');p.add_argument('--d1-dir');p.add_argument('--d2-dir')
    p.add_argument('--import-review',help='Actual user-supplied point/instance JSON; never auto-generated labels')
    p.add_argument('--seq',type=int,default=245847);p.add_argument('--bbox',nargs=6,type=float);p.add_argument('--view')
    a=p.parse_args()
    if a.import_review:
        if not a.case:p.error('--import-review needs --case')
        r=import_human_review(a.case,a.import_review,a.output)
    elif a.init_five:r=five_cases(a.manifest,a.frames,a.output,a.max_points)
    elif a.summarize_d1:
        if not a.cases or not a.d1_dir:p.error('--summarize-d1 needs --cases and --d1-dir')
        r=summarize_cases_d1(a.cases,a.d1_dir,a.output)
    elif a.render_d1:
        if not a.cases or not a.d1_dir:p.error('--render-d1 needs --cases and --d1-dir')
        r=render_cases_d1(a.cases,a.d1_dir,a.output,a.max_points)
    elif a.compare_d2:
        if not a.case or not a.d2_dir:p.error('--compare-d2 needs --case and --d2-dir')
        r=compare_case_d2(a.case,a.d2_dir,a.output,a.max_points)
    elif a.summarize_d2:
        if not a.d2_dir:p.error('--summarize-d2 needs --d2-dir')
        r=summarize_run_d2(a.manifest,a.frames,a.d2_dir,a.output)
    else:
        if a.bbox is None:p.error('Supply --bbox for a new individual RAW case')
        r=export_raw_case(a.manifest,a.frames,a.seq,a.output,roi={'bbox':a.bbox},view=a.view,max_points=a.max_points,
            selection_reason='Explicit geometric selection; material identity UNKNOWN')
    print(json.dumps(json_safe(r),ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':main()
