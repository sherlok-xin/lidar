"""Bounded real ROS1 sequence input and lossless ROS1 debug payload specification.
No ROS nodes. Frozen V1-B IO is imported read-only with bytecode disabled.
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import hashlib, io, json, struct, time
import numpy as np
CROOT = Path(__file__).resolve().parents[1]
BROOT = CROOT.parent
sys.path.insert(0, str(BROOT))
TOPICS = ['/opdf_v1/'+x for x in ('raw','nonground','class_rgb','entity_only','aerosol_strong','unknown','ground','retained','optical_rgb','scan_rgb','spatial_rgb')]
PALETTE = {1:[0,220,180],2:[255,120,0],3:[160,80,220],4:[140,140,140]}
STAGE2 = {'optical_rgb':('optical__optical_weak_score','optical__optical_available'),
          'scan_rgb':('geometry__scan_discontinuity_score','geometry__scan_available'),
          'spatial_rgb':('geometry__spatial_diffuse_score','geometry__spatial_available')}
FIELDS = [{'name':n,'offset':o,'datatype':t,'count':1} for n,o,t in
          [('x',0,7),('y',4,7),('z',8,7),('intensity',12,7),('rgb',16,7),('raw_slot_id',20,6)]]

def write_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False))

def inside(path):
    p=Path(path).resolve()
    try:p.relative_to(CROOT)
    except ValueError:raise ValueError('all writes must stay inside v1c')
    return p

def _header(b):
    seq,sec,nsec,size=struct.unpack_from('<IIII',b,0)
    return {'seq':seq,'stamp_ns':sec*10**9+nsec,'frame_id':b[16:16+size].decode()},16+size

def preview_candidates(bag_path, output_dir=None, *, max_read_bytes=2*1024**2):
    """Only index, record headers and three compressed camera contexts; skip cloud bytes."""
    from opdf.io_rosbag import _BudgetReader,_read_tail_index,_record,_u32,_stamp_ns
    out=inside(output_dir or CROOT/'evidence/selection_preview');out.mkdir(parents=True,exist_ok=False)
    p=Path(bag_path).resolve();beg=time.perf_counter();images=[]
    with p.open('rb') as f:
        reader=_BudgetReader(f,max_read_bytes);fp,conns,chunks=_read_tail_index(reader,p)
        cid=next(k for k,c in conns.items()if c['topic']=='/hesai/pandar_points')
        eligible=[(i,c)for i,c in enumerate(chunks)if c['counts'].get(cid,0)]
        mid=len(eligible)//2
        for tag,index in zip(('before','center','after'),(mid-12,mid,mid+12)):
            ci,ch=eligible[index];reader.seek(ch['offset']);cr=_record(reader,fp['index_pos'])
            if cr['header']['compression']!=b'none':raise ValueError('preview requires audited uncompressed chunk')
            while reader.tell()<cr['end']:
                r=_record(reader,cr['end']);h=r['header']
                if h['op']==b'\x02' and conns.get(_u32(h['conn']),{}).get('type')=='sensor_msgs/CompressedImage':
                    b=reader.read(r['data_length']);hd,pos=_header(b);n=struct.unpack('<I',b[pos:pos+4])[0];fmt=b[pos+4:pos+4+n].decode();pos+=4+n;n=struct.unpack('<I',b[pos:pos+4])[0];jpeg=b[pos+4:pos+4+n]
                    dest=out/f'{tag}.jpg';dest.write_bytes(jpeg)
                    images.append({'tag':tag,'file':str(dest),'topic':conns[_u32(h['conn'])]['topic'],'header':hd,'record_stamp_ns':_stamp_ns(h['time']),'message_file_offset':r['data_offset'],'chunk_index':ci,'format':fmt,'status':'candidate context only; not human material confirmation'})
                    break
                reader.seek(r['end'])
        report={'source_fingerprint':fp,'actual_source_bytes_read':reader.bytes_read,'elapsed_seconds':time.perf_counter()-beg,'images':images,'proposed_cloud_start_ordinal':len(eligible)//2-15,'proposed_count':30,'selection_status':'CANDIDATE_PENDING_HUMAN_REVIEW'}
    write_json(out/'preview_manifest.json',report);return report

def select_continuous_sequence(bag_path, output_dir, *, count=30, start_ordinal=None,
                               max_read_bytes=160*1024**2, selection_reason='', preview_manifest=None):
    from opdf.io_rosbag import _BudgetReader,_read_tail_index,_record,_u32,_stamp_ns,decode_pointcloud2
    if not 30<=count<=60:raise ValueError('candidate count must be 30..60')
    out=inside(output_dir);out.mkdir(parents=True,exist_ok=False);samples=out/'samples';samples.mkdir()
    m={'status':'RUNNING','frames':[],'failures':[],'source_bag':str(Path(bag_path).resolve()),'output_dir':str(out),'selection_reason':selection_reason,'selection_status':'ASSISTANT_SELECTED_CANDIDATE_NOT_HUMAN_CONFIRMED','preview_manifest':str(preview_manifest)if preview_manifest else None,'count_requested':count,'max_read_bytes':max_read_bytes}
    p=Path(bag_path).resolve();started=time.perf_counter();reader=None;payload=0
    try:
        before=p.stat()
        with p.open('rb')as f:
            reader=_BudgetReader(f,max_read_bytes);fp,conns,chunks=_read_tail_index(reader,p);m['source_fingerprint']=fp
            cid=next(k for k,c in conns.items()if c['topic']=='/hesai/pandar_points'and c['type']=='sensor_msgs/PointCloud2')
            ranges=[];ordinal=0
            for i,ch in enumerate(chunks):
                n=ch['counts'].get(cid,0);ranges.append((ordinal,ordinal+n,i));ordinal+=n
            start_ordinal=ordinal//2-count//2 if start_ordinal is None else start_ordinal
            if not 0<=start_ordinal<=ordinal-count:raise ValueError('requested sequence is outside finalized index')
            stop=start_ordinal+count;m.update(start_ordinal=start_ordinal,indexed_cloud_count=ordinal)
            for a,z,ci in ranges:
                if z<=start_ordinal or a>=stop:continue
                ch=chunks[ci];reader.seek(ch['offset']);cr=_record(reader,fp['index_pos'])
                if cr['header']['compression']!=b'none':raise ValueError('continuous extraction supports audited uncompressed chunks only')
                b=reader.read(cr['data_length']);payload+=len(b);s=io.BytesIO(b);local=0
                while s.tell()<len(b):
                    r=_record(s,len(b));h=r['header']
                    if h['op']==b'\x02'and _u32(h['conn'])==cid:
                        index=a+local;local+=1
                        if start_ordinal<=index<stop:
                            raw=s.read(r['data_length']);rn=_stamp_ns(h['time']);loc={'connection_id':cid,'topic':conns[cid]['topic'],'chunk_index':ci,'chunk_file_offset':ch['offset'],'record_offset_in_uncompressed_chunk':r['offset'],'message_file_offset':cr['data_offset']+r['data_offset'],'cloud_ordinal':index,'compression':'none'}
                            frame=decode_pointcloud2(raw,source_bag=str(p),locator=loc,record_stamp_ns=rn,fingerprint=fp);key=f'seq{frame.seq:06d}';dest=samples/f'{key}.ros1msg';meta=frame.metadata();meta.update(key=key,window='continuous30')
                            if dest.exists():raise FileExistsError(dest)
                            dest.write_bytes(raw);write_json(dest.with_suffix('.json'),meta)
                            m['frames'].append({'path':str(dest.relative_to(out)),'metadata_path':str(dest.with_suffix('.json').relative_to(out)),'key':key,'seq':frame.seq,'header_stamp_ns':frame.header_stamp_ns,'record_stamp_ns':rn,'sha256':hashlib.sha256(raw).hexdigest(),'locator':loc,'height':frame.height,'width':frame.width,'window':'continuous30'})
                    s.seek(r['end'])
                if local!=z-a:raise ValueError('chunk count differs from local finalized index')
        rows=m['frames']
        if len(rows)!=count:raise ValueError('selected frame count mismatch')
        if any(y['seq']!=x['seq']+1 or y['header_stamp_ns']<=x['header_stamp_ns']or y['record_stamp_ns']<=x['record_stamp_ns']for x,y in zip(rows,rows[1:])):raise ValueError('sequence is not seq-contiguous with increasing dual timestamps')
        after=p.stat();m['source_stat_unchanged']=before.st_size==after.st_size and before.st_mtime_ns==after.st_mtime_ns
        if not m['source_stat_unchanged']:raise ValueError('source changed during sequence read')
        m['status']='COMPLETE'
    except Exception as e:
        m['status']='FAILED';m['failures'].append({'type':type(e).__name__,'message':str(e)});raise
    finally:
        m.update(actual_bytes_read=reader.bytes_read if reader else 0,chunk_payload_bytes_read=payload,elapsed_seconds=time.perf_counter()-started)
        write_json(out/'manifest.json',m)
    return m

def derived_points(arrays, layer):
    """Pure deterministic export payload, shared by writer and readback validation."""
    xyz=np.asarray(arrays['xyz']);labels=np.asarray(arrays['labels']);valid=np.asarray(arrays['valid_xyz_mask'],bool)&np.isfinite(xyz).all(1)
    masks={'nonground':valid&(labels!=4),'class_rgb':valid,'entity_only':valid&(labels==1),'aerosol_strong':valid&(labels==2),'unknown':valid&(labels==3),'ground':valid&(labels==4),'retained':valid&np.isin(labels,[1,3])}
    if layer in STAGE2:
        score_key,av_key=STAGE2[layer];mask=valid;score=np.asarray(arrays[score_key]);av=np.asarray(arrays[av_key],bool)&np.isfinite(score);rgb=np.full((len(xyz),3),100,np.uint8);v=np.clip(np.nan_to_num(score),0,1)
        rgb[av]=np.column_stack([255*v[av],80*(1-v[av]),255*(1-v[av])]).astype(np.uint8)
    else:
        mask=masks[layer];rgb=np.zeros((len(xyz),3),np.uint8)
        for label,color in PALETTE.items():rgb[labels==label]=color
    slots=np.asarray(arrays['raw_slot_id'])[mask]
    if np.any(slots>np.iinfo(np.uint32).max):raise ValueError('slot exceeds ROS1 debug uint32 range')
    packed=(rgb[:,0].astype(np.uint32)<<16)|(rgb[:,1].astype(np.uint32)<<8)|rgb[:,2].astype(np.uint32)
    dtype=np.dtype({'names':['x','y','z','intensity','rgb_bits','raw_slot_id'],'formats':['<f4','<f4','<f4','<f4','<u4','<u4'],'offsets':[0,4,8,12,16,20],'itemsize':24})
    points=np.empty(int(mask.sum()),dtype=dtype)
    for i,k in enumerate(('x','y','z')):points[k]=xyz[mask,i]
    points['intensity']=np.asarray(arrays['intensity'])[mask];points['rgb_bits']=packed[mask];points['raw_slot_id']=slots.astype(np.uint32)
    return points

def schema():
    return {'topics':TOPICS,'derived_fields':FIELDS,'derived_point_step':24,'derived_height':1,'rgb_encoding':'FLOAT32 field containing exact bits 0x00RRGGBB, not numerical float colors','palette_label_rgb':PALETTE,'stage2':{k:{'score_key':v[0],'available_key':v[1],'meaning':'heatmap only, not material label','unavailable_rgb':[100,100,100],'gradient':'score0 blue [0,80,255], score1 red [255,0,0]'}for k,v in STAGE2.items()},'semantics':{'entity_only':'E only','retained':'E+U only, ground separate','raw':'exact original serialized PointCloud2 including invalid slots/fields/stride','nonground':'finite XYZ excluding G; not free space'},'controls_copied':False}
