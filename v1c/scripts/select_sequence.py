#!/usr/bin/env python3
import sys
sys.dont_write_bytecode=True
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse,json
from opdf_c.sequence_io import CROOT,preview_candidates,select_continuous_sequence
p=argparse.ArgumentParser();p.add_argument('--bag',default='/home/xin/lidar/data/2026-09-17-15-14-07_1.bag');p.add_argument('--preview-only',action='store_true');p.add_argument('--count',type=int,default=30);p.add_argument('--start-ordinal',type=int);p.add_argument('--reason',default='Middle neighborhood contains vehicle-shaped objects and low-altitude diffuse candidates in bounded camera context; material/point correspondence unconfirmed.');a=p.parse_args()
if a.preview_only:r=preview_candidates(a.bag)
else:r=select_continuous_sequence(a.bag,CROOT/'samples/continuous30',count=a.count,start_ordinal=a.start_ordinal,selection_reason=a.reason,preview_manifest=CROOT/'evidence/selection_preview/preview_manifest.json')
print(json.dumps({k:v for k,v in r.items()if k not in ('frames','source_fingerprint')},ensure_ascii=False,indent=2))
