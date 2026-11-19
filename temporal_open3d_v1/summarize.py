"""Assemble recording-macro contrasts only after all registered completions exist."""
import argparse, json,csv,platform,hashlib
from pathlib import Path
import numpy as np
from collections import defaultdict
from evaluate import write_csv

SEEDS=(197,241,3090)
MAIN=('S','T2','TK','TK_F4','TK_REC','TF','N0_pair','N1_pair')
def read(p):return json.loads(p.read_text())
def table(p):
    with p.open() as f:return list(csv.DictReader(f))
def mean(v):return float(np.mean(v))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--analysis',type=Path,required=True);ap.add_argument('--runs',type=Path,required=True);args=ap.parse_args(); root=args.analysis
    events=[]; pooled=[]; macro=[]; contrasts=[];controls=[];worst=[];policy=[];timing=[]; runs=[]; strata_out=[]
    for seed in SEEDS:
        d=root/str(seed);assert read(d/'execution.json')['paired_net'];raw=table(d/'metrics.csv'); ctl=table(d/'matched_controls.csv');strata=table(d/'strata.csv'); ratios=read(d/'policies.json');masks=table(d/'coverage.csv')
        for row in strata:
            if row['model'] in MAIN and row['policy']=='fixed':strata_out.append(dict(seed=seed,**row))
        for mod in dict.fromkeys(row['model'] for row in raw):
            policy.append(dict(seed=seed,model=mod,**ratios[mod]));
            for scope in ('all','matched'):
                recs=[z for z in raw if z['domain']=='uchile' and z['scope']==scope and z['model']==mod and z['event']!='ALL' and z['policy']=='fixed' and z['AP']]
                macro.append(dict(seed=seed,scope=scope,model=mod,n_events=len(recs),labelled=sum(int(z['labelled_scored']) for z in recs),mean_recording_AP=mean([float(z['AP']) for z in recs]),mean_recording_trapezoid_PRAUC=mean([float(z['PR_AUC']) for z in recs])))
                lo=min(recs,key=lambda z:float(z['AP']));worst.append(dict(seed=seed,scope=scope,model=mod,event=lo['event'],AP=lo['AP'],F1=lo['F1'],dust=lo['dust'],labelled=lo['labelled_scored']))
                for z in recs:events.append(dict(seed=seed,**z))
            for z in raw:
                if z['event']=='ALL' and z['model']==mod:pooled.append(dict(seed=seed,**z))
        for a,b in [('T2','S'),('TK','T2'),('TF','S'),('TF','TK'),('TK_F4','TK'),('TK_REC','TK'),('TF','TK_REC'),('N1_pair','N0_pair')]:
            by={m:{e['event']:e for e in events if e['seed']==seed and e['scope']=='matched' and e['model']==m} for m in (a,b)};assert set(by[a])==set(by[b]);
            for e,z in by[a].items():
                v=by[b][e];assert z['labelled_scored']==v['labelled_scored'];contrasts.append(dict(seed=seed,a=a,b=b,event=e,rows=int(z['labelled_scored']),delta_AP=float(z['AP'])-float(v['AP'])))
        for z in ctl:
            if z['AP_control'] and z['AP_TF']:controls.append(dict(seed=seed,a='TF',b=z['control'],event=z['event'],rows=int(z['rows']),delta_AP=float(z['AP_TF'])-float(z['AP_control'])))
        for p in args.runs.glob('temporal_randlav1_*_'+str(seed)):
            fin=read(p/'finished.json');cfg=read(p/'config.json');elog=[json.loads(l) for l in (p/'epochs.jsonl').read_text().splitlines()];runs.append(dict(name=p.name,type='network',seed=seed,code_release='3d644f0896362d0678d2',receipt=str(p/'finished.json'),sha256=digest(p/'finished.json'),train_config_sha=digest(p/'config.json'),weights=fin['checkpoint_sha'],valtest=str(p/'predictions'),source=cfg['manifest_sha256']));timing.append(dict(name=p.name,elapsed_s=fin['total_seconds'],best_epoch=fin['selected_epoch'],epochs=len(elog),updates=sum(row['updates'] for row in elog),GPU=fin['gpu'],peak_bytes=fin['gpu_max_bytes'],timers=json.dumps(fin['timers'])))
        p=args.runs/'temporal_probe_197_r2';rec=read(p/f'run_seed_{seed}.json');weights=p/'weights'/str(seed);runs.append(dict(name=p.name,type='probe',seed=seed,code_release='8cd8ad964f365209cb51',receipt=str(p/f'run_seed_{seed}.json'),sha256=digest(p/f'run_seed_{seed}.json'),train_config_sha=digest(weights/'training.json'),weights=';'.join(f'{f.name}:{digest(f)}' for f in sorted(weights.glob('*.npz'))),valtest=str(p/'scores'/str(seed)),source=rec['source_hashes']['manifest']))
    increments=[]
    for category,records in [('primary',contrasts),('matched_control',controls)]:
        for a,b in sorted({(z['a'],z['b']) for z in records}):
            rs=[z for z in records if z['a']==a and z['b']==b];byseed={s:mean([z['delta_AP'] for z in rs if z['seed']==s]) for s in SEEDS};event={e:mean([z['delta_AP'] for z in rs if z['event']==e]) for e in set(z['event'] for z in rs)};n=sum(v>0 for v in event.values());mm=mean(list(byseed.values()));increments.append(dict(contrast=category,a=a,b=b,seed197=byseed[197],seed241=byseed[241],seed3090=byseed[3090],mean_delta=mm,events_positive=n,events=len(event),over_declared_bar=bool(mm>=.02 and min(byseed.values())>0 and n>len(event)/2)))
    for f,data in [('recording_macro',macro),('pooled',pooled),('paired_differences',contrasts+controls),('increments',increments),('worst_recordings',worst),('risk',policy),('selected_strata',strata_out),('run_manifest',runs),('network_timing',timing)]:write_csv(root/(f+'.csv'),data)
    summary=[]
    for m in MAIN:
        rs=[v['mean_recording_AP'] for v in macro if v['model']==m and v['scope']=='matched'];z=[v for v in pooled if v['scope']=='matched' and v['model']==m]; pp=[v for v in pooled if v['scope']=='all' and v['model']==m and v['domain']=='ped' and v['policy']=='fixed'];vv=[v for v in pooled if v['scope']=='all' and v['model']==m and v['domain']=='follow' and v['policy']=='fixed'];z=[v for v in z if v['policy']=='fixed'];summary.append(dict(model=m,macro_AP_mean=mean(rs),macro_AP_seeds=rs,matched_F1_mean=mean([float(v['F1']) for v in z]),n_per_seed=[int(v['labelled_scored']) for v in z],person_FP=[int(v['person_fp']) for v in pp],person_den=int(pp[0]['person_den']),vehicle_FP=[int(v['vehicle_fp']) for v in vv],vehicle_den=int(vv[0]['vehicle_den']),risk_status=[v['status'] for v in policy if v['model']==m]));
    (root/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    from matplotlib import use
    use('Agg');import matplotlib.pyplot as plt
    fig,ax=plt.subplots(1,2,figsize=(10,4.5),layout='constrained');colors={'S':'#83512e','TF':'#158a78','N0_pair':'#386ab3','N1_pair':'#5e479c','N0_joint':'#93384c'}
    for mod,col in colors.items():
        pol=next(v for v in policy if v['model']==mod and v['seed']==197)
        with np.load(root/'197'/(mod+'_validation_curve.npz')) as z:
            rr=z['dust_tp']/pol['val_dust'];a=z['person_fp']/pol['val_person'];b=z['vehicle_fp']/pol['val_vehicle'];ax[0].plot(100*np.maximum(a,b),100*rr,label=mod,c=col,lw=1.5)
    ax[0].axvline(1,c='black',ls='--',lw=1);ax[0].axhline(10,c='grey',ls=':',lw=1);ax[0].set(xlim=(0,10),ylim=(0,60),xlabel='Larger of person / vehicle suppression (%)',ylabel='Dust recall (%)',title='Pedestrian validation, seed 197');ax[0].legend(fontsize=8)
    for j,m in enumerate(['S','T2','TK','TF','N0_pair','N1_pair']):
        y=next(s['macro_AP_seeds'] for s in summary if s['model']==m);ax[1].scatter(j+np.array([-.11,0,.11]),y,c=['#33618f','#d48539','#4d8568']);ax[1].plot([j-.17,j+.17],[mean(y)]*2,color='black',lw=1)
    ax[1].set(xticks=range(6),xticklabels=['S','T2','TK','TF','N0','N1'],ylabel='Mean recording AP',title='Matched static mining returns, three seeds',ylim=(0,1));fig.savefig(root/'comparison.png',dpi=170);plt.close(fig)
if __name__=='__main__':main()
