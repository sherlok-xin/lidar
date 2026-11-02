#!/usr/bin/env python3
"""Controlled display-only pointwise guard over the immutable D1 candidates.
No local-ground recomputation. D1 source arrays and D2 input contract unchanged.
"""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import argparse,csv,hashlib,json,time
import numpy as np
DROOT=Path(__file__).resolve().parents[1]
NEW_NAMES=('d1__low_clutter_suppressible_mask','d1__low_clutter_deferred_mask','d1__nonground_guarded_display_mask')


def compute_guard(candidate,scan_available,spatial_available,hard_protect,strict):
    values=[np.asarray(x,dtype=bool)for x in (candidate,scan_available,spatial_available,hard_protect,strict)]
    if any(x.ndim!=1 or x.shape!=values[0].shape for x in values):raise ValueError('pointwise guard arrays must share original slot domain')
    candidate,scan,spatial,hard,strict=values
    if np.any(candidate&~strict):raise ValueError('candidate must be subset of strict nonground')
    suppressible=candidate&scan&spatial&~hard
    deferred=candidate&~suppressible
    guarded=strict&~suppressible
    return dict(zip(NEW_NAMES,(suppressible,deferred,guarded)))


def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb')as f:
        for chunk in iter(lambda:f.read(1024**2),b''):h.update(chunk)
    return h.hexdigest()

def dump(path,obj):Path(path).write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False))
def csv_table(path,rows):
    with Path(path).open('w',newline='')as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])if rows else ['key']);w.writeheader();w.writerows(rows)


def main():
    p=argparse.ArgumentParser();p.add_argument('--source-run',type=Path,default=DROOT/'outputs/d1_ground');p.add_argument('--output',type=Path,default=DROOT/'outputs/d1_pointwise_guard');a=p.parse_args();out=a.output.resolve()
    try:out.relative_to(DROOT)
    except ValueError:raise ValueError('new writes only inside v1d')
    out.mkdir(parents=True,exist_ok=False);(out/'frames').mkdir();source_manifest=json.loads((a.source_run/'input_manifest.json').read_text());started=time.perf_counter();rows=[];points=[];entries=[];source_stats=[]
    for entry in source_manifest['frames']:
        t=time.perf_counter();key=entry['key'];source=a.source_run/'frames'/f'{key}.npz';stat0=source.stat();source_sha=sha_file(source)
        with np.load(source,allow_pickle=False)as z:
            slots=z['raw_slot_id'];candidate=z['d1__low_clutter_mask'];scan=z['geometry__scan_available'];spatial=z['geometry__spatial_available'];hard=z['d1__hard_structure_protect_mask'];strict=z['d1__nonground_strict_mask'];legacy=z['d1__nonground_display_mask'];names=list(z.files)
        if not np.array_equal(legacy,strict&~candidate):raise ValueError('immutable source legacy partition inconsistent')
        guarded=compute_guard(candidate,scan,spatial,hard,strict)
        if np.any(legacy&~guarded[NEW_NAMES[2]])or np.any(guarded[NEW_NAMES[1]]&~guarded[NEW_NAMES[2]]):raise ValueError('guard must retain all legacy display and all deferred points')
        path=out/'frames'/f'{key}.npz';np.savez_compressed(path,raw_slot_id=slots,**guarded)
        sidecar={'method':'D1-POINTWISE-DISPLAY-GUARD','key':key,'seq':entry['seq'],'header_stamp_ns':entry['header_stamp_ns'],'record_stamp_ns':entry['record_stamp_ns'],'source_d1_npz':str(source.resolve()),'source_d1_npz_sha256':source_sha,'source_d1_json':str(source.with_suffix('.json').resolve()),'source_d1_json_sha256':sha_file(source.with_suffix('.json')),'source_original_array_names':names,'delta_array_names':['raw_slot_id',*NEW_NAMES],'source_candidate_mask':'d1__low_clutter_mask','default_display_mask':NEW_NAMES[2],'semantics':'display guard only; candidate/suppressible not material truth; deferred retained UNKNOWN','original_D1_arrays_labels_hard_and_D2_contract_unchanged':True,'formula':'suppressible=candidate & scan_available & spatial_available & ~hard; deferred=candidate & ~suppressible; guarded_display=strict & ~suppressible','no_local_ground_recompute':True}
        dump(path.with_suffix('.json'),sidecar)
        stat1=source.stat();source_unchanged=stat0.st_size==stat1.st_size and stat0.st_mtime_ns==stat1.st_mtime_ns
        if not source_unchanged:raise ValueError('source NPZ stat changed')
        with np.load(path,allow_pickle=False)as z:
            if not np.array_equal(z['raw_slot_id'],slots)or any(not np.array_equal(z[k],guarded[k])for k in NEW_NAMES):raise ValueError('delta NPZ readback mismatch')
        row={'key':key,'seq':entry['seq'],'candidate':int(candidate.sum()),'suppressible':int(guarded[NEW_NAMES[0]].sum()),'deferred':int(guarded[NEW_NAMES[1]].sum()),'legacy_display':int(legacy.sum()),'guarded_display':int(guarded[NEW_NAMES[2]].sum()),'source_arrays_count':len(names),'source_stat_unchanged':source_unchanged,'elapsed_ms':(time.perf_counter()-t)*1000};rows.append(row)
        for i in np.flatnonzero(candidate):points.append({'key':key,'seq':entry['seq'],'header_stamp_ns':entry['header_stamp_ns'],'record_stamp_ns':entry['record_stamp_ns'],'raw_slot_id':int(slots[i]),'candidate':True,'scan_available':bool(scan[i]),'spatial_available':bool(spatial[i]),'hard_protect':bool(hard[i]),'suppressible':bool(guarded[NEW_NAMES[0]][i]),'deferred':bool(guarded[NEW_NAMES[1]][i]),'guarded_display_retained':bool(guarded[NEW_NAMES[2]][i]),'material_identity':'UNKNOWN'})
        entries.append({'key':key,'seq':entry['seq'],'path':str(path.relative_to(out)),'metadata_path':str(path.with_suffix('.json').relative_to(out)),'sha256':sha_file(path),'header_stamp_ns':entry['header_stamp_ns'],'record_stamp_ns':entry['record_stamp_ns'],'source_d1_npz':str(source.resolve()),'source_d1_npz_sha256':source_sha});print(json.dumps(row),flush=True)
    summary={'status':'COMPLETE','real_frames':len(rows),'totals':{k:sum(r[k]for r in rows)for k in ['candidate','suppressible','deferred','legacy_display','guarded_display']},'source_D1_unchanged':all(r['source_stat_unchanged']for r in rows),'original_arrays_count_per_source':sorted(set(r['source_arrays_count']for r in rows)),'elapsed_seconds':time.perf_counter()-started,'no_bag_reads':True,'no_local_ground_recompute':True,'method':'controlled pointwise display-guard over unchanged D1 candidate143'}
    csv_table(out/'metrics.csv',rows);csv_table(out/'candidate_slots.csv',points);dump(out/'candidate_slots.json',points);dump(out/'manifest.json',{'output_dir':str(out),'source_run':str(a.source_run.resolve()),'frames':entries,'delta_only':True});dump(out/'run_summary.json',summary);print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
