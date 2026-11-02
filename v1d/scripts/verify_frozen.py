#!/usr/bin/env python3
"""Check the D-entry snapshot; retain pre-existing drift without repairing it."""
from pathlib import Path
import datetime,hashlib,json
D=Path(__file__).resolve().parents[1];B=D.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    snapshot=json.loads((D/'evidence/frozen_baseline.json').read_text());bad=[]
    for base in snapshot['baselines']:
        if sha(Path(base['manifest']))!=base['manifest_sha256']:bad.append(base['manifest'])
        for row in base['files']:
            p=Path(base['root'])/row['path']
            if not p.is_file() or sha(p)!=row['sha256']:bad.append(str(p))
    protected=json.loads((B/'evidence/protected_baseline.json').read_text());r=protected['bag'];p=Path(r['path']);st=p.stat()
    with p.open('rb')as f:head=hashlib.sha256(f.read(4096)).hexdigest()
    if (st.st_size,st.st_mtime_ns,head)!=(r['size'],r['mtime_ns'],r['head4096_sha256']):bad.append('source bag size/mtime/head4096')
    for row in protected['research_ops_files']:
        p=Path(protected['research_ops_root'])/row['path']
        if not p.is_file() or sha(p)!=row['sha256']:bad.append(str(p))
    source=json.loads(Path(protected['source_baseline']).read_text());root=Path(source['root'])
    if {r['path']for r in source['files']}!={str(p.relative_to(root))for p in root.rglob('*')if p.is_file()}:bad.append('engineering file list')
    for row in source['files']:
        p=root/row['path']
        if not p.is_file() or sha(p)!=row['sha256']:bad.append(str(p))
    report=dict(checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),pass_check=not bad,changes=bad,
        snapshot_counts=[len(b['files'])for b in snapshot['baselines']],preexisting_drift=snapshot['preexisting_drift'],
        research_ops_files=len(protected['research_ops_files']),engineering_files=len(source['files']),bag_check='size/mtime/head4096 not whole-file hash')
    (D/'evidence/frozen_check.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return bool(bad)
if __name__=='__main__':raise SystemExit(main())
