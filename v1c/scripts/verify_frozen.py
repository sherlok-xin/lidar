#!/usr/bin/env python3
"""Check frozen V1-B and original inputs; write evidence only in V1-C."""
from pathlib import Path
import datetime
import hashlib
import json

C = Path(__file__).resolve().parents[1]
B = C.parent

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    frozen = json.loads((C/'evidence/v1b_frozen_baseline.json').read_text())
    changes = []
    if sha(B/'DELIVERY_MANIFEST.json') != frozen['v1b_delivery_manifest_sha256']:
        changes.append('V1-B delivery manifest')
    for row in frozen['files']:
        p = B/row['path']
        if not p.is_file() or sha(p) != row['sha256']:
            changes.append('V1-B:'+row['path'])
    old = json.loads((B/'evidence/protected_baseline.json').read_text())
    bag = Path(old['bag']['path']); st = bag.stat()
    with bag.open('rb') as f:
        head = hashlib.sha256(f.read(4096)).hexdigest()
    if (st.st_size, st.st_mtime_ns, head) != (old['bag']['size'],old['bag']['mtime_ns'],old['bag']['head4096_sha256']):
        changes.append('source bag size/mtime/head4096')
    for row in old['research_ops_files']:
        p = Path(old['research_ops_root'])/row['path']
        if not p.is_file() or sha(p) != row['sha256']:
            changes.append('research_ops:'+row['path'])
    src = json.loads(Path(old['source_baseline']).read_text()); base = Path(src['root'])
    expected = {r['path'] for r in src['files']}
    actual = {str(p.relative_to(base)) for p in base.rglob('*') if p.is_file()}
    if expected != actual:
        changes.append('engineering file list changed')
    for row in src['files']:
        p = base/row['path']
        if not p.is_file() or sha(p) != row['sha256']:
            changes.append('engineering:'+row['path'])
    result = dict(checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  pass_check=not changes, changes=changes, frozen_v1b_files=len(frozen['files']),
                  research_ops_files=len(old['research_ops_files']), engineering_files=len(src['files']),
                  bag_check='size/mtime/head4096 only; not full bag hash',
                  output_scope='V1-C only')
    (C/'evidence/frozen_check.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result)); return bool(changes)

if __name__ == '__main__':
    raise SystemExit(main())
