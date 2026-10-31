#!/usr/bin/env python3
"""Verify local input, immutable research records and original engineering."""
from pathlib import Path
import hashlib
import json
import datetime

ROOT=Path(__file__).resolve().parents[1]
b=json.loads((ROOT/'evidence/protected_baseline.json').read_text())
changes=[];row=b['bag'];p=Path(row['path']);st=p.stat()
with p.open('rb')as f:head=hashlib.sha256(f.read(4096)).hexdigest()
if st.st_size!=row['size']or st.st_mtime_ns!=row['mtime_ns']or head!=row['head4096_sha256']:
    changes.append({'input_bag_changed':str(p)})
ops=Path(b['research_ops_root'])
for row in b['research_ops_files']:
    p=ops/row['path']
    if not p.is_file()or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:
        changes.append({'research_ops_changed':row['path']})
src=json.loads(Path(b['source_baseline']).read_text());base=Path(src['root'])
expected={r['path']for r in src['files']};actual={str(p.relative_to(base))for p in base.rglob('*')if p.is_file()}
if expected!=actual:changes.append({'engineering_file_set_changed':sorted(expected^actual)})
for row in src['files']:
    p=base/row['path']
    if not p.is_file()or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:
        changes.append({'engineering_changed':row['path']})
result={'checked_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
        'input_bag_check':'size/mtime/head4096 only, not whole-file hash',
        'research_ops_files':len(b['research_ops_files']),'engineering_files':len(src['files']),
        'changes':changes,'pass':not changes,'writes':'opdf_v1/evidence/protection_check.json only'}
(ROOT/'evidence/protection_check.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2));raise SystemExit(bool(changes))
