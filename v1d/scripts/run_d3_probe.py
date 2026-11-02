#!/usr/bin/env python3
"""After D1/D2 gate, run bounded 30-frame registration feasibility; no label update."""
from pathlib import Path
import sys
sys.dont_write_bytecode=True
D=Path(__file__).resolve().parents[1];B=D.parent;sys.path.insert(0,str(D))
import argparse,hashlib,json,time
import numpy as np
from opdf_d.temporal_probe import voxel_indices,observability,rigid_icp,overlap_probe

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,default=D/'outputs/d2_candidate/fusion');p.add_argument('--output',type=Path,default=D/'outputs/d3_feasibility_final');a=p.parse_args();out=a.output.resolve()
    if not out.is_relative_to(D)or out.exists():raise ValueError('Use a new V1-D output directory')
    full=json.loads((a.run.parent/'run_summary.json').read_text())
    if full['status']!='COMPLETE'or full['real_frames']!=30:raise ValueError('D2 all30 must complete before D3')
    out.mkdir(parents=True);started=time.perf_counter();manifest=json.loads((a.run/'input_manifest.json').read_text());frames=[];sources=[]
    for entry in manifest['frames']:
        f=a.run/'frames'/(entry['key']+'.npz');side=json.loads(f.with_suffix('.json').read_text());m=side['metadata']
        with np.load(f,allow_pickle=False)as z:
            xyz=z['xyz'];valid=z['valid_xyz_mask']&np.isfinite(xyz).all(1);r=np.linalg.norm(xyz,axis=1)
            background=valid&(r>=15)&(r<45)&(xyz[:,2]>-3)&(xyz[:,2]<3)
            bi=voxel_indices(xyz,background);gi=voxel_indices(xyz,background&z['d1__ground_core_mask'])
            coef=np.asarray(side['diagnostics']['modules']['ground']['plane_z_ax_by_c']);normal=np.r_[-coef[:2],1.];normal/=np.linalg.norm(normal)
            normals=np.full((len(bi),3),np.nan);core=z['d1__ground_core_mask'][bi];normals[core]=normal
            available=z['d2__ms_normal_available'][bi,2]&~core
            normals[available]=z['d2__ms_normal'][bi[available],2]
            rois={}
            for name,bounds in [('structure_candidate',[-7,12,-6,6,-.8,3.5]),('aerosol_ambiguity',[7,10,1,4,-1,2.5]),('edge_patch',[6.4,7.1,1.5,2.2,-.3,.4])]:
                b=bounds;mask=valid&(xyz[:,0]>=b[0])&(xyz[:,0]<=b[1])&(xyz[:,1]>=b[2])&(xyz[:,1]<=b[3])&(xyz[:,2]>=b[4])&(xyz[:,2]<=b[5]);ids=voxel_indices(xyz,mask,.05,2000);rois[name]=xyz[ids]
            h,w=int(m['height']),int(m['width'])
            if len(xyz)!=h*w:raise ValueError('Actual cloud shape and raw domain disagree')
            az=np.arctan2(xyz[:,1],xyz[:,0]).reshape(w,h)
            av=valid.reshape(w,h);observed=av.sum(1)>0
            col_az=np.arctan2(np.where(av,np.sin(az),0).sum(1),np.where(av,np.cos(az),0).sum(1));col_az[~observed]=np.nan
            frames.append({'seq':entry['seq'],'background':xyz[bi],'ground':xyz[gi],'column_azimuth':col_az,
                'observability':observability(xyz[bi],normals),'ground_observability':observability(xyz[gi],np.tile(normal,(len(gi),1))),
                'rois':rois,'header_ns':entry['header_stamp_ns'],'record_ns':entry['record_stamp_ns']})
            sources.append({'key':entry['key'],'npz_sha256':sha(f),'selected_background_raw_slots':z['raw_slot_id'][bi].tolist(),
                'background_points':len(bi),'ground_points':len(gi),'original_frame_id':m['frame_id'],
                'header_stamp_ns':entry['header_stamp_ns'],'record_stamp_ns':entry['record_stamp_ns']})
    pairs=[]
    for i in range(len(frames)-1):
        x,y=frames[i:i+2];fit=rigid_icp(x['background'],y['background']);ground_fit=rigid_icp(x['ground'],y['ground']);T=np.asarray(fit['T_target_from_source'])if fit['available']else None
        pair={'source_seq':x['seq'],'target_seq':y['seq'],'delta_header_ns':y['header_ns']-x['header_ns'],
            'delta_record_ns':y['record_ns']-x['record_ns'],'far_background_icp':fit,'ground_only_icp':ground_fit,
            'source_observability':x['observability'],'ground_observability':x['ground_observability'],
            'ROI_overlap':{name:{'raw':overlap_probe(x['rois'][name],y['rois'][name]),'background_aligned':overlap_probe(x['rois'][name],y['rois'][name],T)}for name in x['rois']}}
        if x['column_azimuth'].shape==y['column_azimuth'].shape:
            delta=x['column_azimuth']-y['column_azimuth'];finite=np.isfinite(delta)
            angles=np.abs(np.degrees(np.arctan2(np.sin(delta[finite]),np.cos(delta[finite]))))
            pair['column_angle_probe']={'joint_observed_columns':int(finite.sum()),'median_abs_delta_deg':float(np.median(angles)),
                'p95_abs_delta_deg':float(np.quantile(angles,.95)),'same_firing_phase_certified':False,
                'meaning':'software column angular pattern only; not return correspondence or per-point timing'}
        if i in (0,14,28):
            initial=np.eye(4);initial[0,3]=.15
            alternative=rigid_icp(x['background'],y['background'],initial=initial)
            pair['initialization_counterexample']=alternative
            if fit['available']and alternative['available']:pair['translation_difference_of_initializations_m']=float(np.linalg.norm(np.asarray(fit['T_target_from_source'])[:3,3]-np.asarray(alternative['T_target_from_source'])[:3,3]))
            pair['local_rigid_hypotheses']={name:{'fit':rigid_icp(x['rois'][name],y['rois'][name]),
                'rigid_instance_verified':False,'reason':'CANDIDATE_SPATIAL_ROI_MAY_MIX_OBJECT_GROUND_PARTICLES_OR_OCCLUSION'}for name in x['rois']}
        pairs.append(pair)
    prior=B.parent/'research_ops/reports/bag_multisensor_audit.md'
    summary={'status':'COMPLETE','method':'D3 bounded geometric feasibility only','frames':len(frames),'adjacent_pairs':len(pairs),
        'M4_available':False,'reason_codes':['BACKGROUND_REGISTRATION_CONDITIONAL_NOT_STATIC_TRUTH','UNVERIFIED_RIGID_OBJECT_CORRESPONDENCE'],
        'sensor_limits':['NO_PER_POINT_TIME_NO_DESKEW_CLAIM','NO_DOPPLER_OR_RETURN_ID_USED'],
        'missing_sensor_fields_are_not_alone_a_barrier_to_frame_temporal_methods':True,
        'labels_modified':False,'particle_velocity_inferred':False,'ICP_matching_is_physical_identity':False,
        'near_static_assumption':'conditional geometric probe, not certified platform stationarity',
        'background_rank6_pairs':sum(q['source_observability']['available']for q in pairs),
        'ground_only_rank6_pairs':sum(q['ground_observability']['available']for q in pairs),
        'median_registration_translation_m':float(np.median([q['far_background_icp']['translation_norm_m']for q in pairs if q['far_background_icp']['available']])),
        'median_registration_abs_yaw_deg':float(np.median([abs(q['far_background_icp']['yaw_deg'])for q in pairs if q['far_background_icp']['available']])),
        'prior_multisensor_report':{'path':str(prior),'sha256':sha(prior),'scope':'prior sparse windows, not whole continuous30 pose truth; wheel speed contradictory'}if prior.exists()else None,
        'elapsed_seconds':time.perf_counter()-started,'actual_command':[sys.executable,*sys.argv],
        'source_modules':{str(p):sha(p)for p in [Path(__file__),D/'opdf_d/temporal_probe.py']}}
    for name,obj in [('summary.json',summary),('pairs.json',pairs),('sources.json',sources)]:
        (out/name).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary))
if __name__=='__main__':main()
