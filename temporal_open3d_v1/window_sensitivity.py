"""Compare window lengths without changing the feature family. Never fit a model."""
import argparse
from pathlib import Path
from collections import defaultdict
import numpy as np
from evaluate import ranking,write_csv
from data_protocol import read_manifest

def main():
    a=argparse.ArgumentParser();a.add_argument('--runs',type=Path,required=True);a.add_argument('--manifest',type=Path,required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args();result=[]
    rows=[r for r in read_manifest(args.manifest)['frames'] if r['role']=='test' and r['domain']=='uchile' and len(r['history'])==9];
    for seed in (197,241,3090):
        store=defaultdict(list)
        for row in rows:
            fn=row['uid']+'.npz';ev=row['event']
            with np.load(args.runs/'temporal_probe_197_r2'/'scores'/str(seed)/fn) as z,np.load(args.runs/f'temporal_randlav1_pair_n1_{seed}'/'predictions/test'/fn) as n1:
                assert np.array_equal(n1['original_index'],z['original_index']);base=n1['temporal_available']&(z['code']>0)
                for a,b in [('TK','TK3'),('T2','LAG2'),('T2','LAG4')]:
                    sa,sb=z['score_'+a],z['score_'+b];ok=base&z['avail_'+a]&z['avail_'+b]&np.isfinite(sa)&np.isfinite(sb);store[(a,b,ev)].append((z['code'][ok],sa[ok],sb[ok]))
        for (a,b,ev),parts in store.items():
            c,sa,sb=[np.concatenate(t) for t in zip(*parts)];apa=ranking(c,sa)[0];apb=ranking(c,sb)[0];result.append(dict(seed=seed,a=a,b=b,event=ev,n=len(c),dust=int((c==2).sum()),ap_a=apa,ap_b=apb,delta_AP=apa-apb if apa is not None else None))
    write_csv(args.out/'window_sensitivity.csv',result)
    avg=[]
    for a,b in sorted({(z['a'],z['b']) for z in result}):
        x={s:float(np.mean([z['delta_AP'] for z in result if z['a']==a and z['b']==b and z['seed']==s and z['delta_AP'] is not None])) for s in (197,241,3090)};avg.append(dict(a=a,b=b,d197=x[197],d241=x[241],d3090=x[3090],mean=float(np.mean(list(x.values())))))
    write_csv(args.out/'window_means.csv',avg);print(avg)
if __name__=='__main__':main()
