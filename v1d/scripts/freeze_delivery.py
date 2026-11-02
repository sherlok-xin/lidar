#!/usr/bin/env python3
"""Hash D delivery only, with explicit accepted versus retained-failure products."""
import datetime,hashlib,json
from pathlib import Path
D=Path(__file__).resolve().parents[1]
def digest(p):
    h=hashlib.sha256()
    with p.open('rb')as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    qa=D/'reports/qa_final.md';text=qa.read_text()
    if 'PASS'not in text or '审核进行中，尚未最终签收' in text:
        raise RuntimeError('Final independent QA must precede delivery snapshot')
    trees=('opdf_d','scripts','tests','configs','reports','communications','outputs','evidence')
    files=[p for p in D.iterdir()if p.is_file()and p.name!='DELIVERY_MANIFEST.json']
    for name in trees:
        for p in(D/name).rglob('*'):
            if not p.is_file()or p.is_symlink():continue
            parts=p.relative_to(D).parts
            if any(x.startswith('.')or x in ('__pycache__','tmp','matplotlib','ros_logs','user_ros_logs','qa_pytest_tmp')for x in parts):continue
            files.append(p)
    rows=[]
    for p in sorted(set(files)):
        before=p.stat();h=digest(p);after=p.stat()
        if(before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('File changing during snapshot: '+str(p))
        rows.append(dict(path=str(p.relative_to(D)),bytes=after.st_size,sha256=h))
    manifest=dict(created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),root=str(D),
      scope='D delivery snapshot, not a claim that every retained log/image is accepted evidence',
      accepted_products=['outputs/d1_ground','outputs/d1_pointwise_guard','outputs/d1_roi_final',
          'outputs/raw_five_roi','outputs/d2_candidate','outputs/d2_uniform_off_ablation',
          'outputs/d2_final_full_behavior','outputs/d2_final_five_roi','outputs/d2_final_geometry_five_roi',
          'outputs/d2_final_slot139114_comparison','outputs/d3_feasibility_final',
          'evidence/fixed_gui_d1','evidence/fixed_gui_d2','evidence/ros1_d2_actual_full'],
      retained_not_final=['outputs/d1_ground_failed_initial','outputs/d3_feasibility',
          'evidence/ros1_gui_d1_layers','evidence/ros1_gui_d2_changes'],
      limitations=['no independent material GT','no accuracy/safety/deployment certification',
          'fixed GUI images still show unexplained Global Status Warn','M4 unavailable','not 10Hz'],
      files=rows,total_bytes=sum(r['bytes']for r in rows))
    (D/'DELIVERY_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(file_count=len(rows),total_bytes=manifest['total_bytes'],manifest_sha256=digest(D/'DELIVERY_MANIFEST.json'))))
if __name__=='__main__':main()
