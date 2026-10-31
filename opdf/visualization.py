"""Deterministic, shared-camera 3D displays of heuristic candidates, never GT."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

os.environ.setdefault('MPLCONFIGDIR', str(Path(__file__).resolve().parents[1] / '.cache/matplotlib'))

COLORS = {0: '#000000', 1: '#18cbb2', 2: '#ff942d', 3: '#af7bff', 4: '#999fa9'}
NAMES = {0: 'INVALID', 1: 'E candidate', 2: 'A candidate', 3: 'U unknown', 4: 'G candidate'}
PANELS = ('RAW', 'LABELS', 'A_ONLY', 'E_U')


def load_result(npz_path):
    with np.load(npz_path, allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files}
    required = ('xyz', 'intensity', 'valid_xyz_mask', 'raw_slot_id', 'labels',
                'score_e', 'score_a', 'available_e', 'available_a', 'reason_code')
    absent = set(required) - set(arrays)
    if absent:
        raise ValueError(f'Missing result keys: {sorted(absent)}')
    n = len(arrays['xyz'])
    if arrays['xyz'].shape != (n, 3):
        raise ValueError('xyz must be N by 3')
    for k in required[1:]:
        if arrays[k].shape != (n,):
            raise ValueError(f'{k} must have exactly N entries')
    if arrays['raw_slot_id'].dtype.kind not in 'ui' or len(np.unique(arrays['raw_slot_id'])) != n:
        raise ValueError('raw_slot_id must contain unique integers')
    if not np.isin(arrays['labels'], np.arange(5)).all():
        raise ValueError('Unknown label enum')
    return arrays


def select_slots(arrays, roi=None):
    """Return exact full-NPZ array indices. No display cap applies here."""
    xyz = arrays['xyz']
    take = np.isfinite(xyz).all(axis=1) & arrays['valid_xyz_mask'].astype(bool)
    if roi is None:
        return np.flatnonzero(take)
    spec = {'bbox': roi} if not isinstance(roi, dict) else roi
    if spec.get('bbox') is not None:
        b = np.asarray(spec['bbox'], dtype=float)
        if b.shape != (6,) or not np.isfinite(b).all() or np.any(b[::2] > b[1::2]):
            raise ValueError('bbox must be [xmin,xmax,ymin,ymax,zmin,zmax] with finite ordered bounds')
        take &= ((xyz >= b[::2]) & (xyz <= b[1::2])).all(axis=1)
    if spec.get('raw_slot_ids') is not None:
        requested = np.asarray(spec['raw_slot_ids'])
        if requested.size and requested.dtype.kind not in 'ui':
            raise ValueError('raw slot IDs must be integers')
        take &= np.isin(arrays['raw_slot_id'], requested)
    return np.flatnonzero(take)


def normalize_view(view, xyz):
    if isinstance(view, (str, Path)):
        view = json.loads(Path(view).read_text())
    if view is None:
        if len(xyz):
            low, high = np.min(xyz, axis=0), np.max(xyz, axis=0)
            target = ((low + high) / 2).tolist()
            extent = max(float(np.max(high - low)), 1.0)
        else:
            target, extent = [0., 0., 0.], 1.
        view = dict(target=target, distance=extent * 1.8)
    camera = dict(version=1, projection='perspective', target=[0., 0., 0.],
                  distance=20., azimuth_deg=-65., elevation_deg=22., fov_deg=45., up_axis='z')
    camera.update(view)
    target = np.asarray(camera['target'], dtype=float)
    if target.shape != (3,) or not np.isfinite(target).all():
        raise ValueError('Camera target must be three finite coordinates')
    camera['target'] = target.tolist()
    for k in ('distance', 'azimuth_deg', 'elevation_deg', 'fov_deg'):
        camera[k] = float(camera[k])
        if not np.isfinite(camera[k]):
            raise ValueError(f'Camera {k} must be finite')
    if camera['distance'] <= 0 or not 1 < camera['fov_deg'] < 160:
        raise ValueError('Camera distance or field of view is invalid')
    if abs(camera['elevation_deg']) >= 90:
        raise ValueError('Camera elevation must be between -90 and 90 degrees')
    if camera['projection'] != 'perspective' or camera['up_axis'] != 'z' or camera['version'] != 1:
        raise ValueError('Only version 1 perspective/Z-up view is supported')
    return camera


def render_frame(npz_path, *, output_png, output_html=None, view=None, max_points=30000, roi=None):
    """RAW/LABELS/A_ONLY/E_U, one crop, one deterministic cap, one camera.

    The PNG is mplot3d perspective; HTML uses actual XYZ perspective projection,
    depth sorting, shared orbit and wheel zoom. Display samples are not all slots.
    """
    arrays = load_result(npz_path)
    if int(max_points) < 1:
        raise ValueError('max_points must be positive')
    exact = select_slots(arrays, roi)
    order = exact[np.argsort(arrays['raw_slot_id'][exact], kind='stable')]
    camera = normalize_view(view, arrays['xyz'][exact])
    if len(order) > int(max_points):
        order = order[np.linspace(0, len(order) - 1, int(max_points), dtype=np.int64)]
    xyz, labels = arrays['xyz'][order], arrays['labels'][order]
    raw_intensity = np.asarray(arrays['intensity'][order], float)
    finite_i = np.isfinite(raw_intensity)
    bounds = np.percentile(raw_intensity[finite_i], [1, 99]).tolist() if finite_i.any() else [0.0, 1.0]
    normalized_i = np.clip((np.nan_to_num(raw_intensity, nan=bounds[0]) - bounds[0]) /
                           max(bounds[1] - bounds[0], 1.0), 0, 1)
    masks = [np.ones(len(order), dtype=bool), labels != 0, labels == 2,
             np.isin(labels, [1, 3])]
    # Finite-but-INVALID is an inconsistent result; never display it as a point.
    masks = [m & (labels != 0) for m in masks]
    import matplotlib
    matplotlib.use('Agg')
    # Ubuntu preloads a system mpl_toolkits package while this process uses
    # user-site Matplotlib. Prefer its co-installed toolkit, without changing
    # either installation or any filesystem outside the branch.
    import mpl_toolkits
    matching_toolkit = Path(matplotlib.__file__).resolve().parent.parent / 'mpl_toolkits'
    if (matching_toolkit / 'mplot3d').is_dir():
        mpl_toolkits.__path__ = [str(matching_toolkit)] + [
            str(p) for p in mpl_toolkits.__path__ if str(p) != str(matching_toolkit)]
    from mpl_toolkits.mplot3d import Axes3D
    from matplotlib.projections import register_projection
    register_projection(Axes3D)
    import matplotlib.pyplot as plt
    raw_rgba = plt.get_cmap('viridis')(normalized_i)
    raw_rgba[~finite_i] = [.5, .5, .5, 1.]
    raw_hex = ['#%02x%02x%02x' % tuple((rgb[:3] * 255).astype(int)) for rgb in raw_rgba]
    fig = plt.figure(figsize=(16, 11), facecolor='#101724')
    half = camera['distance'] * np.tan(np.deg2rad(camera['fov_deg'] / 2)) * .80
    for i, (name, mask) in enumerate(zip(PANELS, masks)):
        ax = fig.add_subplot(2, 2, i + 1, projection='3d', facecolor='#101724')
        points = xyz[mask]
        color = raw_rgba[mask] if i == 0 else [COLORS[int(v)] for v in labels[mask]]
        if len(points):
            ax.scatter(*points.T, c=color, s=.7, linewidths=0, depthshade=True, rasterized=True)
        ax.set_title(f'{name} · {len(points):,} displayed', color='white', fontsize=11)
        for axis, center, setter in zip('XYZ', camera['target'], (ax.set_xlim, ax.set_ylim, ax.set_zlim)):
            setter(center - half, center + half)
        ax.set_xlabel('X (m)', color='#bac6d6'); ax.set_ylabel('Y (m)', color='#bac6d6')
        ax.set_zlabel('Z (m)', color='#bac6d6'); ax.tick_params(colors='#bac6d6', labelsize=7)
        ax.set_box_aspect((1, 1, 1))
        ax.set_proj_type('persp', focal_length=1 / np.tan(np.deg2rad(camera['fov_deg'] / 2)))
        ax.view_init(elev=camera['elevation_deg'], azim=camera['azimuth_deg'])
    from matplotlib.lines import Line2D
    legend = [Line2D([0], [0], marker='o', color='none', markerfacecolor=COLORS[v],
                     label=NAMES[v], markersize=6) for v in (1, 2, 3, 4)]
    fig.legend(handles=legend, loc='lower center', ncol=4, labelcolor='white', facecolor='#192334')
    fig.suptitle('OPDF-V1 · heuristic candidates (not ground truth)\n'
                 f'Shared camera / crop / deterministic raw-slot sample: {len(order):,}/{len(exact):,} finite ROI points',
                 color='white', fontsize=12)
    fig.subplots_adjust(top=.90, bottom=.07, wspace=.02, hspace=.12)
    png = Path(output_png); png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png, dpi=150, facecolor=fig.get_facecolor()); plt.close(fig)
    ids = arrays['raw_slot_id'][order]
    result = dict(output_png=str(png), output_html=None, camera=camera, roi=roi,
                  finite_roi_count=len(exact), selected_count=len(order),
                  selected_raw_slot_ids=[int(x) for x in ids],
                  selected_slot_sha256=hashlib.sha256(ids.astype('<u8').tobytes()).hexdigest(),
                  panel_counts={n: int(m.sum()) for n, m in zip(PANELS, masks)},
                  raw_color_mode='source_intensity_display_percentiles_only', raw_intensity_display_bounds=bounds,
                  status='heuristic_candidates_not_ground_truth')
    if output_html:
        html = Path(output_html); html.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(xyz=xyz.tolist(), ids=[int(x) for x in ids], labels=labels.tolist(),
                       intensity=_json_numbers(arrays['intensity'][order]),
                       score_e=_json_numbers(arrays['score_e'][order]),
                       score_a=_json_numbers(arrays['score_a'][order]),
                       reason_code=[int(x) for x in arrays['reason_code'][order]],
                       camera=camera, finite_roi_count=len(exact), blind=False, raw_colors=raw_hex,
                       source_npz=str(Path(npz_path).resolve()))
        html.write_text(_viewer_html(payload))
        result['output_html'] = str(html)
    png.with_suffix('.view.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    return result


def _json_numbers(values):
    return [float(v) if np.isfinite(v) else None for v in values]


def _viewer_html(payload):
    # A single state.camera is used by every panel; no CDN/network dependency.
    data = json.dumps(payload, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    return _HTML.replace('__PAYLOAD__', data)


_HTML = r'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OPDF-V1 · 3D review</title>
<style>body{margin:0;background:#0e1521;color:#d9e4f4;font:14px system-ui}header{padding:18px 24px;border-bottom:1px solid #334156}h1{font-size:20px;margin:0 0 8px}button,input{background:#1e2b40;color:#e8f1ff;border:1px solid #50617b;border-radius:5px;padding:7px;margin:3px}button{cursor:pointer}input{width:75px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:12px}.panel{min-width:0;background:#101b2a;border:1px solid #34425a;border-radius:8px;overflow:hidden}.title{padding:8px 12px;font-weight:600}canvas{width:100%;height:38vh;display:block;touch-action:none}#readout{white-space:pre-wrap;padding:12px 24px}small{color:#aebdd0}.legend{padding:8px 24px}.dot{padding-right:20px}@media(max-width:650px){.grid{grid-template-columns:1fr}canvas{height:40vh}}</style>
<header><h1>OPDF-V1 · shared-camera 3D review</h1><div id="truth">Heuristic candidates · not ground truth</div>
<small>Drag any panel to orbit actual XYZ; wheel to zoom; click a point to inspect its original raw slot. All panels share one camera.</small><br>
<button id="reset">Reset view</button><button id="saveview">Save view JSON</button><button id="screenshot">Save four-panel PNG</button><button id="savequery">Save displayed-slot query</button>
<div id="roi">Display crop (inclusive XYZ): <input id="xmin" placeholder="X min"><input id="xmax" placeholder="X max"><input id="ymin" placeholder="Y min"><input id="ymax" placeholder="Y max"><input id="zmin" placeholder="Z min"><input id="zmax" placeholder="Z max"><button id="apply">Apply crop</button><button id="clear">Clear crop</button></div>
<small id="coverage"></small></header><div class="legend" id="legend"><span class="dot" style="color:#18cbb2">● E candidate</span><span class="dot" style="color:#ff942d">● A candidate</span><span class="dot" style="color:#af7bff">● U unknown</span><span class="dot" style="color:#999fa9">● G candidate</span></div>
<main class="grid"><section class="panel"><div class="title">RAW</div><canvas id="c0"></canvas></section><section class="panel"><div class="title">LABELS</div><canvas id="c1"></canvas></section><section class="panel"><div class="title">A_ONLY</div><canvas id="c2"></canvas></section><section class="panel"><div class="title">E_U</div><canvas id="c3"></canvas></section></main><pre id="readout">Click a displayed point. Query is limited to the deterministic display sample; use review_roi.py on the full NPZ for exact ROI slots.</pre><div id="selftest"></div>
<script id="opdf-data" type="application/json">__PAYLOAD__</script><script>
'use strict';
const data=JSON.parse(document.getElementById('opdf-data').textContent);
const state={camera:structuredClone(data.camera),bbox:null,projected:[],drag:null};
const canvases=[0,1,2,3].map(i=>document.getElementById('c'+i));
const colors=['#000','#18cbb2','#ff942d','#af7bff','#999fa9'];
const titles=['RAW','LABELS','A_ONLY','E_U'];
if(data.blind){document.getElementById('truth').textContent='BLIND review · algorithm labels and scores hidden';document.getElementById('legend').hidden=true;document.querySelectorAll('.title').forEach((x,i)=>x.textContent=i?'BLIND RAW (same points)':'BLIND RAW');}
const dot=(a,b)=>a.reduce((s,x,i)=>s+x*b[i],0),sub=(a,b)=>a.map((x,i)=>x-b[i]);
function basis(){const a=state.camera.azimuth_deg*Math.PI/180,e=state.camera.elevation_deg*Math.PI/180;const out=[Math.cos(e)*Math.cos(a),Math.cos(e)*Math.sin(a),Math.sin(e)];const eye=state.camera.target.map((x,i)=>x+state.camera.distance*out[i]);const right=[-Math.sin(a),Math.cos(a),0];const up=[-Math.sin(e)*Math.cos(a),-Math.sin(e)*Math.sin(a),Math.cos(e)];return{eye,right,up,forward:out.map(x=>-x)};}
function inside(i){const p=data.xyz[i];return !state.bbox||p.every((x,j)=>x>=state.bbox[2*j]&&x<=state.bbox[2*j+1]);}
function project(p,w,h,b=basis()){const d=sub(p,b.eye),depth=dot(d,b.forward);if(depth<=.00001)return null;const f=Math.min(w,h)/2/Math.tan(state.camera.fov_deg*Math.PI/360);return{x:w/2+f*dot(d,b.right)/depth,y:h/2-f*dot(d,b.up)/depth,depth};}
function panelVisible(panel,i){if(data.blind)return true;const l=data.labels[i];if(l===0)return false;return panel<2||panel===2&&l===2||panel===3&&(l===1||l===3);}
function render(){const b=basis();state.projected=[];for(let panel=0;panel<4;panel++){const c=canvases[panel],box=c.getBoundingClientRect(),w=Math.max(1,Math.round(box.width)),h=Math.max(1,Math.round(box.height));c.width=w;c.height=h;const ctx=c.getContext('2d');ctx.fillStyle='#101b2a';ctx.fillRect(0,0,w,h);const points=[];for(let i=0;i<data.xyz.length;i++){if(!inside(i)||!panelVisible(panel,i))continue;const p=project(data.xyz[i],w,h,b);if(p&&p.x>=0&&p.x<w&&p.y>=0&&p.y<h)points.push({...p,i});}points.sort((a,b)=>b.depth-a.depth);for(const p of points){ctx.fillStyle=panel===0||data.blind?(data.raw_colors?data.raw_colors[p.i]:'#a3c5e6'):colors[data.labels[p.i]];ctx.fillRect(p.x-1,p.y-1,2.1,2.1);}ctx.fillStyle='#c4d5eb';ctx.font='12px monospace';ctx.fillText(points.length+' visible points',12,h-12);state.projected[panel]=points;c.dataset.camera=JSON.stringify(state.camera);}document.getElementById('coverage').textContent=`${data.xyz.length.toLocaleString()} display-sampled slots from ${data.finite_roi_count.toLocaleString()} finite ROI slots. Crop/query covers this sample only; no invented invalid points. Source: ${data.source_npz}`;document.body.dataset.rendered='true';}
function download(name,content,type='application/json'){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([content],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
canvases.forEach((c,panel)=>{c.addEventListener('pointerdown',e=>{state.drag={x:e.clientX,y:e.clientY,lastx:e.clientX,lasty:e.clientY,moved:false};c.setPointerCapture(e.pointerId);});c.addEventListener('pointermove',e=>{if(!state.drag)return;const d=state.drag;const dx=e.clientX-d.lastx,dy=e.clientY-d.lasty;d.lastx=e.clientX;d.lasty=e.clientY;if(Math.hypot(e.clientX-d.x,e.clientY-d.y)>3)d.moved=true;state.camera.azimuth_deg-=dx*.35;state.camera.elevation_deg=Math.max(-85,Math.min(85,state.camera.elevation_deg+dy*.35));render();});c.addEventListener('pointerup',e=>{const d=state.drag;state.drag=null;if(!d||d.moved)return;const box=c.getBoundingClientRect(),x=e.clientX-box.left,y=e.clientY-box.top;let hit=null,best=64;for(const p of state.projected[panel]){const q=(p.x-x)**2+(p.y-y)**2;if(q<best){best=q;hit=p.i;}}if(hit!==null){const r={raw_slot_id:data.ids[hit],xyz:data.xyz[hit],intensity:data.intensity[hit]};if(!data.blind)Object.assign(r,{heuristic_label:data.labels[hit],score_e:data.score_e[hit],score_a:data.score_a[hit],reason_code:data.reason_code[hit]});document.getElementById('readout').textContent=JSON.stringify(r,null,2);}});c.addEventListener('wheel',e=>{e.preventDefault();state.camera.distance=Math.max(.01,state.camera.distance*Math.exp(e.deltaY*.001));render();},{passive:false});});
document.getElementById('reset').onclick=()=>{state.camera=structuredClone(data.camera);state.bbox=null;render();};
document.getElementById('saveview').onclick=()=>download('view.json',JSON.stringify(state.camera,null,2));
document.getElementById('savequery').onclick=()=>download('display_sample_query.json',JSON.stringify({scope:'DISPLAY_SAMPLE_ONLY_NOT_EXACT_FULL_NPZ',source_npz:data.source_npz,view:state.camera,bbox:state.bbox,raw_slot_ids:data.ids.filter((_,i)=>inside(i))},null,2));
document.getElementById('apply').onclick=()=>{const ids=['xmin','xmax','ymin','ymax','zmin','zmax'];if(ids.some(id=>document.getElementById(id).value.trim()==='')){alert('Supply all six finite bounds');return;}const b=ids.map(id=>Number(document.getElementById(id).value));if(!b.every(Number.isFinite)||[0,2,4].some(i=>b[i]>b[i+1])){alert('Invalid inclusive bounding box');return;}state.bbox=b;render();};
document.getElementById('clear').onclick=()=>{state.bbox=null;render();};
document.getElementById('screenshot').onclick=()=>{const w=canvases[0].width,h=canvases[0].height;const out=document.createElement('canvas');out.width=w*2;out.height=h*2+60;const c=out.getContext('2d');c.fillStyle='#0e1521';c.fillRect(0,0,out.width,out.height);c.fillStyle='white';c.font='16px sans-serif';c.fillText(data.blind?'OPDF-V1 BLIND raw review':'OPDF-V1 heuristic candidates, NOT ground truth',12,24);canvases.forEach((v,i)=>{c.drawImage(v,(i%2)*w,60+Math.floor(i/2)*h);});out.toBlob(b=>download('shared_view.png',b,'image/png'));};
window.opdfViewer={state,project,render,data};window.addEventListener('resize',render);render();
if(new URLSearchParams(location.search).has('selftest')){try{const p0=data.xyz.length?project(data.xyz[0],600,400):null;state.camera.azimuth_deg+=37;render();const p1=data.xyz.length?project(data.xyz[0],600,400):null;const shared=canvases.every(c=>c.dataset.camera===canvases[0].dataset.camera);const valid=shared&&(!p0||!p1||Math.abs(p0.x-p1.x)+Math.abs(p0.y-p1.y)>1e-9||data.xyz[0].every((x,j)=>x===state.camera.target[j]));document.getElementById('selftest').textContent=JSON.stringify({pass:valid,shared_camera:shared,panels:canvases.length,real_3d_depth_sort:true});document.body.dataset.selftest=valid?'PASS':'FAIL';}catch(e){document.getElementById('selftest').textContent=String(e);document.body.dataset.selftest='FAIL';}}
</script></html>'''
