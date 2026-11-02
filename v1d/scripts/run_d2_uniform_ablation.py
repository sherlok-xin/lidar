#!/usr/bin/env python3
"""One-parameter optical ablation; reuse stored D2 features, never recompute PCA."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
DROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(DROOT))
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2');os.environ.setdefault('OMP_NUM_THREADS','2')
import argparse,copy,csv,hashlib,json,time
import numpy as np,yaml
from opdf_d.fusion import fuse,STANDARD_FIELDS

ROIS={'vehicle_structure_candidate':[-7,12,-6,6,-.8,3.5],
 'near_ground_rough_vegetation_candidate':[3,18,-16,-6,-1.8,-.5],
 'aerosol_surface_ambiguity':[7,10,1,4,-1,2.5],
 'vehicle_body_edge_candidate':[4,7,-2,2,-.6,1.6],
 'possible_low_obstacle_unknown':[7,9,5,7,-1.5,-.9]}
C_KEYS=('aerosol_suspect_mask','aerosol_suspect_available_mask','suspect_uniform_low_mask',
 'entity_optical_conflict_mask','suspect_protected_mask','suspect_evidence_count','suspect_reason_code')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def ah(a):return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
def dump(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def ch(cfg):return hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def table(path,rows):
    with Path(path).open('w',newline='')as f:
        w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys()for r in rows))));w.writeheader();w.writerows(rows)
def counts(labels,mask):return {name:int(np.count_nonzero(mask&(labels==i)))for name,i in [('INVALID',0),('E',1),('A',2),('U',3),('G',4)]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-run',type=Path,default=DROOT/'outputs/d2_candidate')
    p.add_argument('--output',type=Path,default=DROOT/'outputs/d2_uniform_off_ablation')
    args=p.parse_args();src=args.source_run.resolve();out=args.output.resolve()
    if not out.is_relative_to(DROOT)or out==DROOT:raise ValueError('Writes restricted to new v1d subdirectory')
    if out.exists():raise FileExistsError(out)
    parent_summary=json.loads((src/'run_summary.json').read_text())
    if parent_summary.get('status')!='COMPLETE'or parent_summary.get('real_frames')!=30:raise ValueError('Wait for full D2 thirty COMPLETE')
    source_cfg=yaml.safe_load((src/'config_snapshot.yaml').read_text());cfg=copy.deepcopy(source_cfg)
    if cfg['d2']['uniform_low_enabled'] is not True:raise ValueError('Expected uniform-on original source')
    cfg['d2']['uniform_low_enabled']=False
    expected=copy.deepcopy(source_cfg);expected['d2']['uniform_low_enabled']=False
    if cfg!=expected:raise ValueError('Only uniform_low_enabled may change')
    method_hashes=json.loads((src/'method_sources.json').read_text())
    source_checks={path:sha(path)==digest for path,digest in method_hashes.items()}
    if not all(source_checks.values()):raise ValueError('Frozen D2 source/config changed before ablation')
    manifest=json.loads((src/'input_manifest.json').read_text());entries=manifest['frames']
    if len(entries)!=30:raise ValueError('Need thirty exact source entries')
    out.mkdir(parents=True);(out/'frames').mkdir();(out/'changes').mkdir()
    (out/'config_snapshot.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False))
    dump(out/'input_manifest.json',manifest)
    dump(out/'method_sources.json',{'source_run_method_hashes':method_hashes,
        'source_hashes_still_match':source_checks,'ablation_script_sha256':sha(__file__),
        'fusion_source_sha256':sha(DROOT/'opdf_d/fusion.py')})
    started=time.perf_counter();rows=[];roi_rows=[];verification=[];source_digests={}
    all_transitions=np.zeros((5,5),np.int64)
    with(out/'actual.log').open('w')as log:
        log.write('ACTUAL_COMMAND '+repr([sys.executable,*sys.argv])+'\n');log.flush()
        for entry in entries:
            key=entry['key'];source=src/'fusion/frames'/f'{key}.npz';t=time.perf_counter()
            with np.load(source,allow_pickle=False)as z:a={k:z[k]for k in z.files}
            meta=json.loads(source.with_suffix('.json').read_text())
            if meta['d2_config_sha256']!=ch(source_cfg):raise ValueError('D2 source config mismatch')
            old=a['labels'];valid=a['valid_xyz_mask']&np.isfinite(a['xyz']).all(1);n=len(old)
            b=dict(a)
            for name in STANDARD_FIELDS:b[name]=a['b__'+name]
            load_ms=(time.perf_counter()-t)*1000
            feature_keys=[k for k in a if k.startswith('d2__ms_')or k in [
                'd2__hard_plane_support','d2__hard_line_support','d2__hard_structure_any_scale',
                'd2__volume_candidate','d2__geometry_conflict','d2__normal_consistency',
                'd2__line_axis_consistency','d2__feature_approximation_mask']]
            ms={'arrays':{k:a[k]for k in feature_keys}}
            # Source B, D1, C7 and shared geometry cross-checks independent of prior runner assertions.
            t=time.perf_counter();d1=Path(meta['source_d1_npz']);d1_meta=json.loads(d1.with_suffix('.json').read_text())
            checks={'D1_source_file_hash':sha(d1)==meta['source_d1_npz_sha256'],
             'raw_slots_exact_arange':np.array_equal(a['raw_slot_id'],np.arange(n,dtype=np.uint64)),
             'valid_exact_XYZ_finiteness':np.array_equal(a['valid_xyz_mask'],np.isfinite(a['xyz']).all(1)),
             'original_B_48_array_hashes':all(ah(b[k])==v for k,v in d1_meta['source_original_array_sha256'].items()),
             'new_A_only_original_U':not np.any(a['d2__new_A_mask']&(a['b__labels']!=3)),
             'new_A_protection_union_zero':not np.any(a['d2__new_A_mask']&a['d2__hard_protection_union']),
             'no_direct_E_A':not np.any((a['b__labels']==1)&(a['labels']==2)),
             'B_G_identity':np.array_equal(a['labels']==4,a['b__labels']==4)}
            with np.load(d1,allow_pickle=False)as z:
                checks['all_D1_aux_exact']=all(ah(a[k])==ah(z[k])for k in z.files if k not in STANDARD_FIELDS)
            cp=DROOT.parent/'v1c/outputs/v1c_uniform_pair/frames'/f'{key}.npz'
            with np.load(cp,allow_pickle=False)as z:checks['C7_exact_existing_frozen_C']=all(ah(a[k])==ah(z[k])for k in C_KEYS)
            gp=src/'geometry_only/frames'/f'{key}.npz'
            with np.load(gp,allow_pickle=False)as z:
                checks['both_modes_same_ms_features']=all(ah(a[k])==ah(z[k])for k in feature_keys)
                checks['geometry_only_no_new_A']=not np.any((z['labels']==2)&(z['b__labels']!=2))
                checks['geometry_only_B_G_identity']=np.array_equal(z['labels']==4,z['b__labels']==4)
                checks['geometry_only_B_decision_backups']=all(ah(z['b__'+k])==ah(a['b__'+k])for k in STANDARD_FIELDS)
                checks['both_modes_C7_exact']=all(ah(z[k])==ah(a[k])for k in C_KEYS)
            if not all(checks.values()):raise AssertionError({'key':key,'checks':checks})
            verify_ms=(time.perf_counter()-t)*1000
            t=time.perf_counter();result=fuse(b,ms,cfg,ablation='fusion');compute_ms=(time.perf_counter()-t)*1000
            new=result['arrays']['labels'];added=(new==2)&(old!=2);lost=(old==2)&(new!=2)
            if added.any():raise AssertionError('Disabling a positive optical cue must not add A')
            if np.any((new==1)!=(old==1))or np.any((new==4)!=(old==4)):raise AssertionError('Optical ablation changed E/G')
            if not np.array_equal(new==0,old==0):raise AssertionError('Optical ablation changed INVALID')
            delta={'raw_slot_id':a['raw_slot_id'],**{k:result['arrays'][k]for k in STANDARD_FIELDS},
                'b__labels':a['b__labels'],'source_fusion_labels':old}
            change={'added_A_raw_slot_id':a['raw_slot_id'][added],'lost_A_raw_slot_id':a['raw_slot_id'][lost],
                'changed_raw_slot_id':a['raw_slot_id'][new!=old],
                'before_label':old[new!=old],'after_label':new[new!=old],
                'new_reason_code':result['arrays']['reason_code'][new!=old]}
            source_sha=sha(source);source_digests[key]=source_sha
            dmeta={'method':'OPDF-V1-D2-uniform-off-single-change','version':'0.1.0',
                'metadata':meta['metadata'],'source_D2_fusion_npz':str(source),
                'source_D2_fusion_npz_sha256':source_sha,'source_D2_metadata_sha256':sha(source.with_suffix('.json')),
                'source_config_sha256':ch(source_cfg),'ablation_config_sha256':ch(cfg),
                'only_changed_parameter':{'d2.uniform_low_enabled':{'before':True,'after':False}},
                'geometry_recomputed':False,'C7_source':'read-only source D2 NPZ retains original C domain; not recomputed',
                'incremental_output':'XYZ/I/ms/D1/C fields remain in source NPZ; labels/reason retained here',
                'fusion_diagnostics':result['diagnostics'],'source_cross_checks':checks,'no_independent_GT':True}
            t=time.perf_counter();np.savez_compressed(out/'frames'/f'{key}.npz',**delta)
            np.savez_compressed(out/'changes'/f'{key}.npz',**change);dump(out/'frames'/f'{key}.json',dmeta)
            write_ms=(time.perf_counter()-t)*1000
            matrix=np.zeros((5,5),np.int64);np.add.at(matrix,(old,new),1);all_transitions+=matrix
            row={'key':key,'seq':entry['seq'],'slots':n,'finite':int(valid.sum()),**counts(new,np.ones(n,bool)),
                'added_A_vs_uniform_on':int(added.sum()),'lost_A_vs_uniform_on':int(lost.sum()),
                'new_A_vs_B':int(((new==2)&(a['b__labels']!=2)).sum()),
                'source_load_ms':load_ms,'cross_source_verify_ms':verify_ms,'fuse_only_ms':compute_ms,'serialize_ms':write_ms}
            rows.append(row);verification.append({'key':key,'checks':checks})
            xyz=a['xyz']
            for name,box in ROIS.items():
                m=valid&(xyz[:,0]>=box[0])&(xyz[:,0]<=box[1])&(xyz[:,1]>=box[2])&(xyz[:,1]<=box[3])&(xyz[:,2]>=box[4])&(xyz[:,2]<=box[5])
                roi_rows.append({'key':key,'seq':entry['seq'],'roi':name,'finite':int(m.sum()),
                    **{'on_'+k:v for k,v in counts(old,m).items()},**{'off_'+k:v for k,v in counts(new,m).items()},
                    'added_A':int((m&added).sum()),'lost_A':int((m&lost).sum()),'roi_identity':'UNKNOWN_candidate_coordinates'})
            log.write(json.dumps(row)+'\n');log.flush();print(json.dumps(row),flush=True)
    table(out/'metrics.csv',rows);table(out/'roi_counts.csv',roi_rows);dump(out/'source_verification.json',verification)
    checks_after={str(path):sha(path)==digest for path,digest in method_hashes.items()}
    source_files_unchanged=all(sha(src/'fusion/frames'/f'{key}.npz')==digest for key,digest in source_digests.items())
    if not all(checks_after.values())or not source_files_unchanged:raise AssertionError('Frozen source changed during evaluation')
    summary={'status':'COMPLETE','real_frames':len(rows),'only_parameter_changed':'d2.uniform_low_enabled true -> false',
        'source_run':str(src),'source_config_sha256':ch(source_cfg),'ablation_config_sha256':ch(cfg),
        'geometry_recomputed':False,'new_multiscale_runs':0,'new_bag_reads':0,
        'aggregate':{k:sum(r[k]for r in rows)for k in ['slots','finite','INVALID','E','A','U','G',
         'added_A_vs_uniform_on','lost_A_vs_uniform_on','new_A_vs_B']},
        'uniform_on_to_off_matrix':all_transitions.tolist(),'source_hashes_still_match':checks_after,
        'D2_fusion_NPZ_sources_unchanged':source_files_unchanged,'all_30_cross_source_checks_passed':True,
        'timing_median_ms':{k:float(np.median([r[k]for r in rows]))for k in ['source_load_ms','cross_source_verify_ms','fuse_only_ms','serialize_ms']},
        'total_elapsed_seconds':time.perf_counter()-started,'no_independent_GT':True,
        'interpretation':'candidate behavior change, not improvement/optimal parameters or deletion safety'}
    dump(out/'run_summary.json',summary);print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
