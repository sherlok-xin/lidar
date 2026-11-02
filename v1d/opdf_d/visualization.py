"""V1-D views built on read-only frozen XYZ/ROI/camera/blind helpers."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode=True
DROOT=Path(__file__).resolve().parents[1];BASE=DROOT.parent
os.environ['MPLCONFIGDIR']=str(DROOT/'.cache/matplotlib')
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['TMPDIR']=str(DROOT/'.cache/tmp')
Path(os.environ['TMPDIR']).mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(BASE))
import numpy as np
from opdf.visualization import load_result,select_slots,normalize_view

_spec=importlib.util.spec_from_file_location('frozen_review_for_d',BASE/'scripts/review_roi.py')
_old=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_old)

D1_KEYS={'GroundCore':'ground_core_mask','LowClutter':'low_clutter_mask',
         'NongroundStrict':'nonground_strict_mask','NongroundDisplay':'nonground_display_mask'}


def safe_output(path):
    p=Path(path).resolve()
    if not p.is_relative_to(DROOT):raise ValueError('All new artifacts must stay under v1d')
    p.parent.mkdir(parents=True,exist_ok=True)
    return p


def mask_array(arrays,name):
    key='d1__'+name
    if key not in arrays:raise ValueError(f'Missing D1 diagnostic array {key}')
    value=np.asarray(arrays[key])
    if value.shape!=(len(arrays['xyz']),) or value.dtype.kind!='b':
        raise ValueError(f'{key} must be an exact slot-aligned bool mask')
    return value


def render_d1_views(npz_path,*,output_png,view=None,max_points=12000,roi=None):
    """Five actual-XYZ panels; cap once, all category counts remain full ROI."""
    a=load_result(npz_path);exact=select_slots(a,roi)
    if max_points<1:raise ValueError('max_points must be positive')
    order=exact[np.argsort(a['raw_slot_id'][exact],kind='stable')]
    camera=normalize_view(view,a['xyz'][exact])
    if len(order)>max_points:order=order[np.linspace(0,len(order)-1,max_points,dtype=np.int64)]
    masks={'RAW':np.ones(len(a['xyz']),bool)}
    masks.update({k:mask_array(a,v) for k,v in D1_KEYS.items()})
    counts={k:int(m[exact].sum()) for k,m in masks.items()}
    displayed={k:int(m[order].sum()) for k,m in masks.items()}
    import matplotlib
    matplotlib.use('Agg')
    import mpl_toolkits
    toolkit=Path(matplotlib.__file__).resolve().parent.parent/'mpl_toolkits'
    if (toolkit/'mplot3d').is_dir():
        mpl_toolkits.__path__=[str(toolkit)]+[str(p) for p in mpl_toolkits.__path__ if str(p)!=str(toolkit)]
    from mpl_toolkits.mplot3d import Axes3D
    from matplotlib.projections import register_projection
    register_projection(Axes3D)
    import matplotlib.pyplot as plt
    fig=plt.figure(figsize=(17,10),facecolor='#111a29')
    colors={'GroundCore':'#a5adba','LowClutter':'#f4d35e','NongroundStrict':'#29c3cc','NongroundDisplay':'#b49bf4'}
    half=camera['distance']*np.tan(np.deg2rad(camera['fov_deg']/2))*.8
    for panel,(name,mask) in enumerate(masks.items(),1):
        ax=fig.add_subplot(2,3,panel,projection='3d',facecolor='#111a29')
        pick=order[mask[order]];xyz=a['xyz'][pick]
        if len(pick):
            color=np.ma.masked_invalid(a['intensity'][pick]) if name=='RAW' else colors[name]
            ax.scatter(*xyz.T,c=color,cmap='viridis' if name=='RAW' else None,s=1.2,linewidths=0)
        ax.set_title(f'{name}\nFull ROI {counts[name]:,} / shown {displayed[name]:,}',color='white',fontsize=10)
        for i,setter in enumerate((ax.set_xlim,ax.set_ylim,ax.set_zlim)):
            setter(camera['target'][i]-half,camera['target'][i]+half)
        ax.set_box_aspect((1,1,1));ax.set_proj_type('persp',focal_length=1/np.tan(np.deg2rad(camera['fov_deg']/2)))
        ax.view_init(elev=camera['elevation_deg'],azim=camera['azimuth_deg'])
        ax.set_xlabel('X m');ax.set_ylabel('Y m');ax.set_zlabel('Z m');ax.tick_params(colors='#bdcbdf',labelsize=6)
    notes=fig.add_subplot(2,3,6);notes.axis('off')
    notes.text(0,.9,'D1 diagnostic sets, not semantic truth\n\n'
        'One shared camera / crop / raw-slot sample.\nCounts use ALL finite selected slots.\n'
        'LowClutter is not A or certified soft material.\nStrict/display are different debug products.\n'
        'Missing/invalid is never free space.',color='white',fontsize=12,va='top',linespacing=1.8)
    fig.suptitle('V1-D1 actual XYZ · diagnostic masks only',color='white',fontsize=15)
    fig.subplots_adjust(top=.88,bottom=.06,wspace=.03,hspace=.24)
    out=safe_output(output_png);fig.savefig(out,dpi=140,facecolor=fig.get_facecolor());plt.close(fig)
    source_path=Path(npz_path).resolve();side_path=source_path.with_suffix('.json')
    side=json.loads(side_path.read_text()) if side_path.exists() else {}
    meta=side.get('metadata',side)
    finite=np.isfinite(a['xyz']).all(1)&a['valid_xyz_mask']
    core=masks['GroundCore'];clutter=masks['LowClutter'];strict=masks['NongroundStrict'];display=masks['NongroundDisplay']
    summary=dict(npz_path=str(source_path),source_npz_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
      source_sidecar=str(side_path) if side_path.exists() else None,
      source_sidecar_sha256=hashlib.sha256(side_path.read_bytes()).hexdigest() if side_path.exists() else None,
      raw_message_sha256=meta.get('raw_message_sha256'),header_stamp_ns=meta.get('header_stamp_ns'),record_stamp_ns=meta.get('record_stamp_ns'),
      original_labels_unchanged=side.get('original_labels_unchanged'),
      contract_diagnostics=dict(core_clutter_overlap=int((core&clutter&finite).sum()),
        strict_definition_mismatch=int((strict!=(finite&~core)).sum()),
        display_definition_mismatch=int((display!=(strict&~clutter)).sum()),
        masks_mark_invalid_slots=int(((core|clutter|strict|display)&~finite).sum())),
      camera=camera,roi=roi,finite_roi_count=len(exact),
      full_roi_counts=counts,display_counts=displayed,display_sample_count=len(order),
      display_raw_slot_ids=[int(x) for x in a['raw_slot_id'][order]],
      display_slot_sha256=hashlib.sha256(a['raw_slot_id'][order].astype('<u8').tobytes()).hexdigest(),
      labels_G_roi_count=int((a['labels'][exact]==4).sum()),
      d1_ground_available_roi_count=int(mask_array(a,'ground_available')[exact].sum()) if 'd1__ground_available' in a else None,
      hard_structure_protect_roi_count=int(mask_array(a,'hard_structure_protect_mask')[exact].sum()) if 'd1__hard_structure_protect_mask' in a else None,
      color_semantics='D1 diagnostic sets, not E/A/U/G material labels; GroundCore differs from labels G',performance_computed=False)
    out.with_suffix('.view.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
    return summary


def render_raw_context(npz_paths,*,output_png,view=None,max_points=12000,roi=None):
    """Read-only reuse of old blind 3D renderer; no algorithm answer embedded."""
    from PIL import Image,ImageDraw
    from opdf.visualization import _viewer_html
    paths=[Path(p).resolve() for p in npz_paths]
    arrays=[load_result(p) for p in paths]
    exact=[_old.exact_selection(a,roi) for a in arrays]
    visible=[idx[np.isfinite(a['xyz'][idx]).all(1)&a['valid_xyz_mask'][idx]] for a,idx in zip(arrays,exact)]
    all_xyz=np.concatenate([a['xyz'][idx] for a,idx in zip(arrays,visible)])
    camera=normalize_view(view,all_xyz)
    out=safe_output(output_png);subdir=out.parent/(out.stem+'_frames');subdir.mkdir(exist_ok=False)
    images=[];rows=[]
    for path,a,indices in zip(paths,arrays,exact):
        target=subdir/(path.stem+'.png')
        payload=_old._blind_screenshot(a,indices,target,camera,max_points)
        payload['source_npz']=str(path)
        target.with_suffix('.html').write_text(_viewer_html(payload))
        im=Image.open(target).convert('RGB');images.append(im)
        rows.append(dict(source_npz=str(path),exact_selected_count=len(indices),
             displayed_count=len(payload['ids']),displayed_raw_slot_ids=payload['ids'],
             source_frame_only_slot_identity=True))
    width=sum(im.width for im in images);height=max(im.height for im in images)+45
    canvas=Image.new('RGB',(width,height),'#111a29');draw=ImageDraw.Draw(canvas)
    offset=0
    for path,im in zip(paths,images):
        canvas.paste(im,(offset,45));draw.text((offset+15,10),path.stem+' | RAW only / no physical correspondence assumed',fill='white');offset+=im.width
    canvas.save(out)
    summary=dict(camera=camera,roi=roi,frames=rows,blind=True,
       adjacency='neighboring source frames; raw_slot_id is NOT physical point correspondence',
       material_truth='UNKNOWN',human_review='PENDING_HUMAN_REVIEW')
    out.with_suffix('.view.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
    return summary
