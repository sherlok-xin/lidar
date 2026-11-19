"""Full-cloud causal evaluation. Fitting a cutoff reads pedestrian validation only."""
import argparse,csv,json,hashlib,time
from pathlib import Path
from collections import defaultdict
from functools import lru_cache
import numpy as np
from sklearn.metrics import precision_recall_curve,average_precision_score,auc
from data_protocol import load_frame,read_manifest
from temporal import Field,FINE,REGION,FAMILY

def write_csv(p,rows):
    if not rows: return
    with p.open('w') as out:
        w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def div(a,b): return float(a/b) if b else None

def ranking(c,s):
    valid=(c>0)&np.isfinite(s); c=c[valid]==2; s=s[valid]
    if not c.any():return None,None
    p,r,_=precision_recall_curve(c,s)
    return float(average_precision_score(c,s)),float(auc(r,p))

def op(c,r,s,t):
    finite=np.isfinite(s); pred=finite&(s>=t); y=c==2; neg=c==1
    tp=int((pred&y).sum()); fp=int((pred&neg).sum()); fn=int((y&finite&~pred).sum())
    pe=r==1; ve=r==2
    return dict(rows=len(c),scored=int(finite.sum()),labelled_scored=int(((c>0)&finite).sum()),dust=int(y.sum()),tp=tp,fp=fp,fn=fn,tn=int((neg&finite&~pred).sum()),precision=div(tp,tp+fp),recall=div(tp,tp+fn),F1=div(2*tp,2*tp+fp+fn),IoU=div(tp,tp+fp+fn),person_fp=int((pe&pred).sum()),person_den=int((finite&pe).sum()),vehicle_fp=int((ve&pred).sum()),vehicle_den=int((ve&finite).sum()),ignore=int((c==0).sum()),ignore_candidates=int(((c==0)&pred).sum()),boundary_candidates=int(((r==4)&pred).sum()),candidate_all=int(pred.sum()))

def risk(c,r,s,frames):
    if np.any(((r==1)|(r==2))&(c!=1)):raise ValueError('entity label mismatch')
    keep=(c>0)&np.isfinite(s); c,r,s,frames=[x[keep] for x in (c,r,s,frames)]
    ix=np.argsort(-s,kind='stable'); u=s[ix]; end=np.flatnonzero(np.r_[u[:-1]!=u[1:],True]) if len(u) else np.empty(0,int)
    def cum(mask):return np.cumsum(mask[ix],dtype='i8')[end]
    tp,pf,vf=cum(c==2),cum(r==1),cum(r==2); dust,pe,ve=[int(x.sum()) for x in (c==2,r==1,r==2)]
    pn,vn=[int(len(np.unique(frames[r==j]))) for j in (1,2)]
    curve=dict(threshold=u[end],dust_tp=tp,person_fp=pf,vehicle_fp=vf)
    budget=(100*pf<=pe)&(100*vf<=ve); support=pe>=100 and ve>=100 and pn>=3 and vn>=3 and dust>0
    best=int(tp[budget].max(initial=0)); ready=support and 10*best>=dust; threshold=None
    if ready:
        i=np.flatnonzero(budget&(tp==best));total=pf[i]+vf[i];threshold=float(u[end[i[total.argmin()]]])
    return dict(status='AVAILABLE' if ready else 'UNAVAILABLE',threshold=threshold,val_person=pe,val_vehicle=ve,val_dust=dust,person_frames=pn,vehicle_frames=vn,maximum_budget_recall=div(best,dust),reason='met' if ready else ('insufficient entity/dust support' if not support else 'dust recall below 10 percent')),curve

def build_context(rows,reference):
    @lru_cache(32)
    def past(source):
        desc=histmap[source]; f=load_frame(desc,labels=False); xyz=f['xyz'][f['valid']].astype('d');return Field(xyz,FINE),Field(xyz,REGION),xyz.min(0),xyz.max(0)
    histmap={x['source']:x for row in rows for x in row['history']}; parts=defaultdict(list); offsets=[0]; frames=[]; timing=[]
    for i,row in enumerate(rows):
        f=load_frame(row); v=f['valid']; xyz=f['xyz'][v].astype('d'); field=Field(xyz,FINE); den=np.zeros(len(v),np.int32); den[v]=field.count[field.addresses(xyz)].astype('i4'); pers=np.zeros(len(v),bool)
        if len(row['history'])>=3:
            num=np.zeros(len(xyz),np.uint8);comp=num.copy()
            for hist in row['history']:
                fine,region,lo,hi=past(hist['source']); seen=((xyz>=lo-FINE)&(xyz<=hi+FINE)).all(1)&(region.addresses(xyz)>0);comp+=seen;num+=seen&(fine.addresses(xyz)>0)
            pers[v]=(comp>=3)&(3*num.astype(int)>=2*comp)
        with np.load(reference/(row['uid']+'.npz')) as z:
            for key in ('code','ref','original_index','valid'):
                if not np.array_equal(f[key],z[key]):raise ValueError((row['uid'],key))
            for k in ('visibility','available','range'):parts[k].append(z[k]);
            core=v.copy() if row['domain']=='uchile' and row['temporal_status']=='T0' and len(row['history'])>=3 else np.zeros_like(v)
            for name in ('S','T2','TK','TF'):core&=z['avail_'+name]
            parts['core'].append(core)
            for name in FAMILY:parts['mask_'+name].append(z['avail_'+name])
            costs=z['feature_seconds'];timing.append(dict(uid=row['uid'],role=row['role'],read_s=float(costs[0]),real_features_s=float(costs[1]),controls_s=float(costs[2]),infer_all_s=float(z['inference_seconds']),history_points=int(z['history_input_points']),copy_points=int(z['copy_input_points']),distant_points=int(z['distant_input_points'])))
        for k in ('original_index','ref','code','valid'):parts[k].append(f[k]);
        parts['density'].append(den);parts['persistent'].append(pers);parts['frame'].append(np.full(len(v),i,np.int16));frames.append(row);offsets.append(offsets[-1]+len(v))
    return {k:np.concatenate(v) for k,v in parts.items()},offsets,timing

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--runs',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--seeds',type=int,nargs='+',default=[197,241,3090]);args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    rows=[r for r in read_manifest(args.manifest)['frames'] if r['role']!='train']; probe=args.runs/'temporal_probe_197_r2';assert (probe/'run_seed_197.json').exists(); x,off,timing=build_context(rows,probe/'scores/197');write_csv(args.out/'probe_frame_costs.csv',timing)
    role=np.array([r['role'] for r in rows]);domain=np.array([r['domain'] for r in rows]);events=np.array([r['event'] for r in rows]); fid=x['frame']; c=x['code'];r=x['ref']; valid=x['valid']; val=((role=='val')&(domain=='ped'))[fid]; idx=x['original_index']; testgroups={}
    for dom in np.unique(domain):
        for e in ['ALL']+sorted(set(events[domain==dom])):
            m=(role=='test')&(domain==dom)
            if e!='ALL':m&=events==e
            if m.any():testgroups[(dom,e)]=m[fid]
    for seed in args.seeds:
        if not (probe/('run_seed_%s.json'%seed)).exists():continue
        names=list(FAMILY); nets={}
        for scope,model in [('public','n0'),('joint','n0'),('pair','n0'),('pair','n1')]:
            p=args.runs/f'temporal_randlav1_{scope}_{model}_{seed}'
            if (p/'finished.json').exists():nets[model.upper()+'_'+scope]=p
        names+=list(nets); scores={k:np.empty(len(c),np.float32) for k in names};n1mask=np.zeros(len(c),bool)
        for i,row in enumerate(rows):
            sl=slice(off[i],off[i+1]);fn=row['uid']+'.npz'
            with np.load(probe/'scores'/str(seed)/fn) as z:
                for key in ('original_index','code','ref','valid'):
                    if not np.array_equal(z[key],x[key][sl]):raise ValueError((fn,key,seed))
                for name in FAMILY:
                    if not np.array_equal(z['avail_'+name],x['mask_'+name][sl]):raise ValueError('availability drift')
                    scores[name][sl]=z['score_'+name]
            for name,p in nets.items():
                with np.load(p/'predictions'/row['role']/fn) as z:
                    for k in ('original_index','code','ref'):
                        if not np.array_equal(z[k],x[k][sl]):raise ValueError((p,fn,k))
                    scores[name][sl]=z['score'];assert np.array_equal(np.isfinite(z['score']),z['predicted_mask'])
                    if name=='N1_pair':n1mask[sl]=z['temporal_available']
        paired_net='N1_pair' in nets and 'N0_pair' in nets
        common=x['core'].copy()
        if paired_net:
            common&=n1mask&np.isfinite(scores['N1_pair'])&np.isfinite(scores['N0_pair']);assert np.array_equal(scores['N1_pair'][~n1mask],scores['N0_pair'][~n1mask],equal_nan=True)
        for name in ('S','T2','TK','TF'):common&=np.isfinite(scores[name]);
        common_scope='matched' if paired_net else 'probe_matched_only'; dest=args.out/str(seed);dest.mkdir(exist_ok=True); measures=[]; matched=[]; strata=[]; coverage=[];policies={}; begin=time.monotonic()
        for name in names:
            s=scores[name]; pol,curve=risk(c[val],r[val],s[val],fid[val]);policies[name]=pol;np.savez_compressed(dest/(name+'_validation_curve.npz'),**curve)
            avail=(x['mask_'+name] if name in FAMILY and name!='S' else n1mask if name=='N1_pair' else np.zeros(len(c),bool));temporal=name not in ('S','N0_public','N0_joint','N0_pair'); pred=np.isfinite(s)
            for (dom,ev),block in testgroups.items():
                for scope,mask in [('all',block), (common_scope,block&common)] if dom=='uchile' else [('all',block)]:
                    if not mask.any():continue
                    sc=s[mask];cd=c[mask];rf=r[mask];ap,pr=ranking(cd,sc)
                    for policy,th in [('fixed',.5),('risk',pol['threshold'])]:
                        if th is None:continue
                        measures.append(dict(model=name,domain=dom,event=ev,scope=scope,policy=policy,threshold=th,AP=ap,PR_AUC=pr,**op(cd,rf,sc,th)))
                if ev!='ALL':continue
                coverage.append(dict(model=name,domain=dom,all_source=int(block.sum()),valid=int((block&valid).sum()),predicted=int((block&pred).sum()),labelled=int((block&(c>0)).sum()),labelled_predicted=int((block&(c>0)&pred).sum()),temporal_input_points=int((block&avail&pred).sum()),fallback_points=int((block&~avail&pred).sum()) if temporal else 0,unpredicted=int((block&~pred).sum())))
                limits=[0,1,2,4,8,np.inf] if dom=='uchile' else [0,8,16,32,np.inf]; conditions=[(f'range_{a}_{b}',(x['range']>=a)&(x['range']<b)) for a,b in zip(limits,limits[1:])];conditions.extend([('sparse_non_dust_proxy',(x['density']<=2)&(c==1)),('dense_persistent_dust',(x['density']>=8)&x['persistent']&(c==2)),('out_of_support',x['visibility']==1),('ambiguous_visibility',x['visibility']==4),('no_history_or_pose',np.isin(x['visibility'],[2,3]))]);
                for kind,m in conditions:
                    where=block&m
                    for policy,th in [('fixed',.5),('risk',pol['threshold'])]:
                        if th is not None:strata.append(dict(model=name,domain=dom,stratum=kind,policy=policy,**op(c[where],r[where],s[where],th)))
            if name in FAMILY and name not in ('S','T2','TK','TF'):
                for (dom,event),block in testgroups.items():
                    if dom!='uchile' or event=='ALL':continue
                    m=block&common&x['mask_'+name]&np.isfinite(s)&(c>0)
                    if m.any():matched.append(dict(control=name,event=event,scope=common_scope,rows=int(m.sum()),dust=int((c[m]==2).sum()),AP_control=ranking(c[m],s[m])[0],AP_TF=ranking(c[m],scores['TF'][m])[0]))
        for file,data in [('metrics',measures),('coverage',coverage),('strata',strata),('matched_controls',matched)]:write_csv(dest/(file+'.csv'),data)
        (dest/'policies.json').write_text(json.dumps(policies,indent=2,allow_nan=False));(dest/'execution.json').write_text(json.dumps(dict(seed=seed,models=names,paired_net=paired_net,elapsed_s=time.monotonic()-begin,manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest()),indent=2)); print(seed,names,len(measures),flush=True)
if __name__=='__main__':main()
