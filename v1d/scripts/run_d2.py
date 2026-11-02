#!/usr/bin/env python3
"""D2 offline candidates from approved frozen D1 thirty-frame arrays. No ROS."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
DROOT=Path(__file__).resolve().parents[1];BROOT=DROOT.parent
sys.path.insert(0,str(DROOT));sys.path.insert(0,str(BROOT/'v1c'))
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2');os.environ.setdefault('OMP_NUM_THREADS','2')
import argparse,csv,hashlib,json,shutil,time
import numpy as np,yaml
from opdf_d.multiscale import compute
from opdf_d.fusion import fuse,STANDARD_FIELDS
from opdf_c.suspect import compute as original_c_aux


def dump(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def filehash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def arrhash(a):return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
def cfg_hash(cfg):return hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def table(path,rows):
    if not rows:return
    with Path(path).open('w',newline='')as f:
        writer=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys()for r in rows))));writer.writeheader();writer.writerows(rows)
def distribution(x):
    x=np.asarray(x);x=x[np.isfinite(x)]
    return {'n':int(len(x)),'p05_p50_p95':np.quantile(x,[.05,.5,.95]).tolist()if len(x)else None}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run',type=Path,default=DROOT/'outputs/d1_ground')
    parser.add_argument('--output',type=Path,default=DROOT/'outputs/d2_candidate')
    parser.add_argument('--config',type=Path,default=DROOT/'configs/d2.yaml')
    parser.add_argument('--seq',type=int,action='append')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(DROOT)or out==DROOT:raise ValueError('All D2 writes must be inside v1d')
    if out.exists():raise FileExistsError(out)
    cfg=yaml.safe_load(args.config.read_text());basecfg=yaml.safe_load((BROOT/'configs/v1b.yaml').read_text())
    source_manifest=json.loads((args.source_run/'input_manifest.json').read_text())
    entries=[r for r in source_manifest['frames']if not args.seq or r['seq']in args.seq]
    if not entries:raise ValueError('No existing frozen inputs selected')
    if any(r['seq']<245832 or r['seq']>245861 for r in entries):raise ValueError('Only approved continuous30 seq245832..245861')
    out.mkdir(parents=True);shutil.copyfile(args.config,out/'config_snapshot.yaml')
    dump(out/'input_manifest.json',{**source_manifest,'frames':entries})
    methods=[DROOT/'opdf_d/multiscale.py',DROOT/'opdf_d/fusion.py',Path(__file__),args.config,BROOT/'v1c/opdf_c/suspect.py']
    dump(out/'method_sources.json',{str(p.resolve()):filehash(p)for p in methods})
    modes=['geometry_only','fusion'];rows=[];dist=[];transitions=[];started=time.perf_counter()
    for mode in modes:
        (out/mode/'frames').mkdir(parents=True)
        shutil.copyfile(args.config,out/mode/'config_snapshot.yaml')
        dump(out/mode/'input_manifest.json',{**source_manifest,'frames':entries})
    with(out/'actual.log').open('w')as log:
        log.write('ACTUAL_COMMAND '+repr([sys.executable,*sys.argv])+'\n');log.flush()
        for entry in entries:
            key=entry['key'];source=args.source_run/'frames'/f'{key}.npz';t=time.perf_counter()
            with np.load(source,allow_pickle=False)as z:base={k:z[k]for k in z.files}
            meta=json.loads(source.with_suffix('.json').read_text())
            if meta.get('config_sha256')!=cfg_hash(basecfg):raise ValueError('Original B configuration mismatch')
            bkeys=list(meta['source_original_array_sha256'])
            if len(bkeys)!=48:raise ValueError(f'Expected original frozen 48 B arrays, got {len(bkeys)}')
            original={k:base[k]for k in bkeys};basehash={k:arrhash(a)for k,a in base.items()}
            if any(basehash[k]!=meta['source_original_array_sha256'][k]for k in bkeys):raise ValueError('D1 original B field modified')
            load_ms=(time.perf_counter()-t)*1000
            t=time.perf_counter();c_aux=original_c_aux(original,basecfg,{'uniform_low_enabled':True});c_ms=(time.perf_counter()-t)*1000
            if len(c_aux)!=7:raise ValueError('Expected seven original C-domain auxiliary arrays')
            t=time.perf_counter();ms=compute(base,meta,cfg);feature_ms=(time.perf_counter()-t)*1000
            valid=base['valid_xyz_mask']&np.isfinite(base['xyz']).all(1)
            n=len(valid);old=base['labels'];source_sha=filehash(source)
            for mode in modes:
                t=time.perf_counter();result=fuse(base,ms,cfg,ablation=mode);fusion_ms=(time.perf_counter()-t)*1000
                arrays={**base,**c_aux,**ms['arrays'],**result['arrays']}
                if any(arrays[k].shape!=v.shape or arrays[k].dtype!=v.dtype or arrhash(arrays[k])!=basehash[k]for k,v in base.items()if k not in STANDARD_FIELDS):raise ValueError('Non-decision original field changed')
                if any(arrhash(arrays['b__'+k])!=basehash[k]for k in STANDARD_FIELDS):raise ValueError('B decision backup mismatch')
                if any(np.asarray(v).ndim==0 or len(v)!=n for v in arrays.values()):raise ValueError('Lost original slot alignment')
                if not np.array_equal(arrays['raw_slot_id'],base['raw_slot_id']):raise ValueError('Raw identity changed')
                new=arrays['labels'];matrix=np.zeros((5,5),np.int64)
                np.add.at(matrix,(old,new),1)
                diff={}
                for name,mask in [('new_E',(new==1)&(old!=1)),('lost_E',(old==1)&(new!=1)),
                                  ('new_A',(new==2)&(old!=2)),('lost_A',(old==2)&(new!=2)),('all_changes',new!=old)]:
                    diff[name+'__raw_slot_id']=base['raw_slot_id'][mask]
                    diff[name+'__before']=old[mask];diff[name+'__after']=new[mask]
                    diff[name+'__d2_reason']=arrays['reason_code'][mask]
                dmeta={**meta,'method':'OPDF-V1-D2-'+mode,'standard_labels_are_D_candidates':True,
                    'source_d1_npz':str(source.resolve()),'source_d1_npz_sha256':source_sha,
                    'B_original_48_preserved_including_b_decisions':True,'D1_aux_preserved':True,
                    'C_aux_domain':'original B48 before D label exchange; not recomputed on D labels',
                    'C_aux_sha256':{k:arrhash(v)for k,v in c_aux.items()},
                    'd2_config_sha256':cfg_hash(cfg),'d2_multiscale_diagnostics':ms['diagnostics'],
                    'd2_fusion_diagnostics':result['diagnostics'],'B_to_D_transition_matrix':matrix.tolist(),
                    'D_G_source':'B original fixed; D1 GroundCore separate display only',
                    'no_independent_GT':True,'diagnostic_candidate_not_deployment':True}
                t=time.perf_counter();dest=out/mode/'frames'/f'{key}.npz'
                np.savez_compressed(dest,**arrays);np.savez_compressed(out/mode/'frames'/f'{key}_changes.npz',**diff)
                dump(dest.with_suffix('.json'),dmeta);write_ms=(time.perf_counter()-t)*1000
                t=time.perf_counter()
                with np.load(dest,allow_pickle=False)as check:
                    for k in STANDARD_FIELDS:
                        if arrhash(check['b__'+k])!=basehash[k]:raise ValueError('Serialized B decision backup differs')
                    if not np.array_equal(check['raw_slot_id'],base['raw_slot_id']):raise ValueError('Serialized slot identity changed')
                verify_ms=(time.perf_counter()-t)*1000
                row={'key':key,'seq':entry['seq'],'ablation':mode,'status':result['diagnostics']['status'],
                     'slots':n,'finite':int(valid.sum()),**result['diagnostics']['counts'],
                     **{k:result['diagnostics'][k]for k in ['new_E','new_A','E_to_U','A_to_U']},
                     'multiscale_available_all':int(ms['arrays']['d2__ms_available'].all(1).sum()),
                     'volume_candidate':int(ms['arrays']['d2__volume_candidate'].sum()),
                     'source_read_hash_ms':load_ms,'C_aux_compute_ms':c_ms,'shared_multiscale_ms':feature_ms,
                     'fusion_ms':fusion_ms,'serialize_ms':write_ms,'readback_ms':verify_ms,
                     **result['diagnostics']['invariant_violations']}
                rows.append(row);log.write(json.dumps(row)+'\n');log.flush();print(json.dumps(row),flush=True)
                transitions.append({'key':key,'seq':entry['seq'],'ablation':mode,'matrix':matrix.tolist()})
            for s,name in enumerate(cfg['d2']['scales']):
                use=ms['arrays']['d2__ms_available'][:,s]
                dist.append({'key':key,'scale':name,'available':int(use.sum()),
                 **{k:distribution(ms['arrays']['d2__ms_'+k][:,s][use])for k in [
                  'full_neighbor_count','sample_count','effective_support_radius_m','radius_m','sampling_fraction',
                  'linearity','planarity','isotropy','scattering','octant_occupancy','phase_support']}})
    table(out/'metrics.csv',rows);dump(out/'transitions.json',transitions);dump(out/'scale_distributions.json',dist)
    summary={'status':'COMPLETE','real_frames':len(entries),'ablation_runs':len(rows),'source_D1_run':str(args.source_run.resolve()),
             'config_sha256':cfg_hash(cfg),'elapsed_seconds':time.perf_counter()-started,
             'D1_GATE':'MASTER PROCEED_D2 received 2026-11-01 18:59 Asia/Shanghai',
             'shared_features_computed_once_per_frame':True,'sample_caps':cfg['d2']['sample_caps'],
             'no_independent_GT':True,'geometry_only_new_A_must_be_zero':True,
             'source_B_G_fixed':True,'C7_original_B_domain':True,'all_invariants_checked':True,
             'aggregate':{mode:{k:sum(r[k]for r in rows if r['ablation']==mode)for k in [
                 'slots','finite','INVALID','E','A','U','G','new_E','new_A','E_to_U','A_to_U']}for mode in modes},
             'timing_median_ms':{k:float(np.median([r[k]for r in rows]))for k in [
                 'source_read_hash_ms','C_aux_compute_ms','shared_multiscale_ms','fusion_ms','serialize_ms','readback_ms']},
             'scope':'new offline D2 candidate classes; not B/C modification, no GT efficacy or safety claim'}
    dump(out/'run_summary.json',summary)
    for mode in modes:
        mode_rows=[r for r in rows if r['ablation']==mode]
        table(out/mode/'metrics.csv',mode_rows)
        dump(out/mode/'run_summary.json',{**summary,'ablation':mode,
            'aggregate':summary['aggregate'][mode],'parent_shared_features_run':str(out),
            'timing_note':'shared_multiscale computed once per source frame, reused by both modes'})
        shutil.copyfile(out/'method_sources.json',out/mode/'method_sources.json')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
