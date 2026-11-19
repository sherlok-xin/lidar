"""Compose private inventories or inspect one real frame. No training, no implicit conversion."""
import argparse,csv,hashlib,json,os,tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datahub import read_frame

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def write_csv(path,rows):
    if not rows:raise ValueError('nothing to publish: '+str(path))
    cols=list(dict.fromkeys(k for r in rows for k in r));tmp=path.with_suffix('.csv.tmp')
    with tmp.open('x',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols,lineterminator='\n');w.writeheader();w.writerows(rows)
    if path.exists() and path.read_bytes()!=tmp.read_bytes():
        tmp.unlink();raise FileExistsError(f'different existing table: {path}; choose a new version')
    tmp.replace(path)

def compose(d):
    tables=[('native','native_dataset_index.csv','native_sequence_groups.csv'),('bag','bag_index.csv','bag_groups.csv')]
    rows=[];groups=[]
    for family,index,rels in tables:
        if not (d/index).is_file() or not (d/rels).is_file():raise FileNotFoundError(f'incomplete component: {family}')
        for r in read(d/index):
            if not r.get('sequence_id'):raise ValueError('missing sequence identity')
            ref=r.get('manifest_ref','')
            if ref:
                p=(d/ref).resolve(strict=True);assert p.is_relative_to(d.resolve())
            rows.append(dict(component=family,**r))
        groups.extend(dict(component=family,**r) for r in read(d/rels))
    if len({(r['dataset_id'],r['sequence_id']) for r in rows})!=len(rows):raise ValueError('duplicate rows')
    write_csv(d/'dataset_index.csv',rows);write_csv(d/'sequence_groups.csv',groups)
    print(json.dumps({'indexed':len(rows),'relations':len(groups)},ensure_ascii=False))

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['compose','list','sample']);p.add_argument('--sequence');p.add_argument('--dataset');p.add_argument('--order',type=int);p.add_argument('--stored',action='store_true')
    a=p.parse_args();d=Path(os.environ['DERIVED_ROOT']).resolve(strict=True)
    if a.command=='compose':return compose(d)
    rows=read(d/'dataset_index.csv')
    if a.dataset:rows=[r for r in rows if r['dataset_id']==a.dataset]
    if a.sequence:rows=[r for r in rows if r['sequence_id']==a.sequence]
    if a.command=='list':
        for r in rows:print(r.get('dataset_id'),r.get('sequence_id'),r.get('format'),r.get('frames'),r.get('eligibility'))
        return
    data=Path(os.environ['DATA_ROOT']).resolve(strict=True)
    for r in rows:
        if not r.get('manifest_ref'):continue
        stream=(d/r['manifest_ref']).resolve(strict=True);assert stream.is_relative_to(d)
        with stream.open() as f:
            for line in f:
                row=json.loads(line)
                if a.order is not None and row['frame_order']!=a.order:continue
                sample=read_frame(row,data_root=data,derived_root=d,valid_only=not a.stored)
                import numpy as np
                print(json.dumps({'uid':row['frame_uid'],'sequence':r['sequence_id'],'order':row['frame_order'],'stored':len(sample['stored_valid_mask']),'valid':int(sample['stored_valid_mask'].sum()),'output_rows':len(sample['xyz']),'task_counts':np.bincount(sample['task_label'],minlength=3).tolist(),'attribute_available':sample['attribute_available'],'first_source_indices':sample['source_point_index'][:5].tolist()},ensure_ascii=False));return
    raise SystemExit('no accessible matching frame; inventory-only entries have no point sample')
if __name__=='__main__':main()
