"""Read a bounded ROS1 bag v2 window without ROS master, reindexing or source writes."""
import bz2
import hashlib
import io
import json
import struct
from pathlib import Path

import numpy as np

PC2="1158d486dd51d683ce2f1be655c3c181"
SCAN="ff6baa58985b528481871cbaf1bb342f"
PACKET="1e4288e00b9222ea477b73350bf24f51"
TYPES={1:"i1",2:"u1",3:"i2",4:"u2",5:"i4",6:"u4",7:"f4",8:"f8"}


def u32(data):return struct.unpack("<I",data)[0]
def sha(data):return hashlib.sha256(data).hexdigest()


def ns(data):
    sec,nsec=struct.unpack("<II",data)
    if nsec>=1000000000:raise ValueError("malformed ROS time")
    return sec*1000000000+nsec


def fields(buf):
    out={};pos=0
    while pos<len(buf):
        length=u32(buf[pos:pos+4]);pos+=4
        if length<2 or pos+length>len(buf):raise ValueError("bag header field span")
        key,value=buf[pos:pos+length].split(b"=",1);pos+=length
        if key in out:raise ValueError("duplicate header key")
        out[key]=value
    return out


def record(stream,limit):
    start=stream.tell()
    size=u32(stream.read(4))
    if size>1048576 or stream.tell()+size+4>limit:raise ValueError("invalid record header")
    header=fields(stream.read(size));length=u32(stream.read(4));payload=stream.tell()
    if payload+length>limit:raise ValueError("invalid record body")
    return start,header,length,payload


class Bag:
    def __init__(self,path,budget=96<<20):
        self.path=Path(path);self.file=self.path.open("rb");self.bytes=0;self.budget=budget
        self.size=self.path.stat().st_size
        self.connections={};self.chunks=[];self.chunk_times=[]
        try:
            if self.read(13)!=b"#ROSBAG V2.0\n":raise ValueError("not indexed ROS1 v2")
            _,first,_,_=record(self,self.size)
            if first[b"op"]!=b"\x03":raise ValueError("not a bag header")
            index=struct.unpack("<Q",first[b"index_pos"])[0]
            if index<self.tell() or index>=self.size:raise ValueError("not finalized or truncated")
            self.file.seek(0)
            self.identity=sha(self.read(min(65536,self.size))+struct.pack("<QQ",self.size,index))
            self.file.seek(index)
            while self.tell()<self.size:
                _,head,count,_=record(self,self.size)
                data=self.read(count)
                if head[b"op"]==b"\x07":
                    connection=fields(data)
                    key=u32(head[b"conn"])
                    self.connections[key]={k:connection[k.encode()].decode() for k in ("type","md5sum","message_definition")}
                    self.connections[key]["topic"]=head[b"topic"].decode()
                elif head[b"op"]==b"\x06":
                    if len(data)!=8*u32(head[b"count"]):raise ValueError("malformed chunk info")
                    pos=struct.unpack("<Q",head[b"chunk_pos"])[0]
                    self.chunks.append((pos,dict(struct.iter_unpack("<II",data))))
                    self.chunk_times.append((ns(head[b"start_time"]),ns(head[b"end_time"])))
            if len(self.chunks)!=u32(first[b"chunk_count"]) or len(self.connections)!=u32(first[b"conn_count"]):
                raise ValueError("incomplete footer")
        except Exception:
            self.file.close();raise

    def read(self,count):
        if count<0 or self.bytes+count>self.budget:raise ValueError("read byte budget exhausted")
        data=self.file.read(count);self.bytes+=len(data)
        if len(data)!=count:raise EOFError("short bag read")
        return data

    def tell(self):return self.file.tell()
    def __enter__(self):return self
    def __exit__(self,*unused):self.file.close()

    def topic(self,name,datatype,md5):
        candidates=[i for i,c in self.connections.items() if c["topic"]==name]
        if len(candidates)!=1:raise ValueError("expected exactly one topic connection")
        connection=self.connections[candidates[0]]
        if connection["type"]!=datatype or connection["md5sum"]!=md5:
            raise ValueError("native message contract mismatch; no type substitution")
        return candidates[0]

    def messages(self,cids,start=0):
        taken={cid:0 for cid in cids}
        for chunk_pos,counts in sorted(self.chunks):
            if not any(counts.get(cid,0) for cid in cids):continue
            if len(cids)==1:
                only=next(iter(cids));n=counts.get(only,0)
                if taken[only]+n<=start:taken[only]+=n;continue
            self.file.seek(chunk_pos)
            _,head,length,_=record(self,self.size)
            if head[b"op"]!=b"\x05" or u32(head[b"size"])>64<<20:raise ValueError("unsupported chunk size/type")
            zipped=self.read(length)
            if head[b"compression"]==b"none":raw=zipped
            elif head[b"compression"]==b"bz2":raw=bz2.BZ2Decompressor().decompress(zipped,max_length=u32(head[b"size"])+1)
            elif head[b"compression"]==b"lz4":
                from lz4.frame import LZ4FrameDecompressor
                codec=LZ4FrameDecompressor()
                raw=codec.decompress(zipped,max_length=u32(head[b"size"])+1)
                if not codec.eof or codec.unused_data:raise ValueError("malformed LZ4 frame")
            else:raise ValueError("unsupported chunk compression: "+repr(head[b"compression"]))
            if len(raw)!=u32(head[b"size"]):raise ValueError("inconsistent chunk expansion")
            inside=io.BytesIO(raw)
            while inside.tell()<len(raw):
                loc,sub,count,payload=record(inside,len(raw))
                if sub[b"op"]==b"\x02" and u32(sub[b"conn"]) in cids:
                    cid=u32(sub[b"conn"]);ordinal=taken[cid];taken[cid]+=1
                    if ordinal>=start:
                        yield cid,ordinal,ns(sub[b"time"]),{"chunk_file_offset":chunk_pos,"decompressed_record_offset":loc},raw[payload:payload+count]
                inside.seek(payload+count)


class Cursor:
    def __init__(self,data):self.data=data;self.pos=0
    def take(self,n):
        if n<0 or self.pos+n>len(self.data):raise ValueError("short ROS message")
        out=self.data[self.pos:self.pos+n];self.pos+=n;return out
    def integer(self):return u32(self.take(4))
    def string(self):return self.take(self.integer()).decode()
    def header(self):return self.integer(),ns(self.take(8)),self.string()


def pointcloud(msg):
    reader=Cursor(msg);seq,stamp,frame=reader.header()
    height,width=reader.integer(),reader.integer();schema=[];count=reader.integer()
    if count>128:raise ValueError("excessive point fields")
    for i in range(count):
        schema.append(dict(name=reader.string(),offset=reader.integer(),datatype=reader.take(1)[0],count=reader.integer(),key="field_%d"%i))
    big=reader.take(1)[0];step,row_step=reader.integer(),reader.integer()
    raw=reader.take(reader.integer());dense=reader.take(1)[0]
    if reader.pos!=len(msg) or len(raw)!=height*row_step or row_step<width*step or big not in (0,1):
        raise ValueError("malformed PointCloud2 strides or payload; no padding inference")
    names={};arrays={}
    for desc in schema:
        dtype=np.dtype((">" if big else "<")+TYPES[desc["datatype"]]);n=desc["count"]
        if n<1 or desc["offset"]+n*dtype.itemsize>step or desc["name"] in names:raise ValueError("invalid/duplicate PointField")
        values=(np.ndarray((height,width,n),dtype=dtype,buffer=raw,offset=desc["offset"],strides=(row_step,step,dtype.itemsize)).reshape(height*width,n).copy()
                if height*width else np.empty((0,n),dtype))
        values=values if n>1 else values[:,0]
        names[desc["name"]]=values;arrays[desc["key"]]=values
    if any(key not in names or names[key].ndim!=1 for key in ("x","y","z")):raise ValueError("missing scalar XYZ")
    xyz=np.column_stack([names[k] for k in ("x","y","z")])
    intensity=names.get("intensity",np.full(len(xyz),np.nan,dtype=np.float32))
    if intensity.ndim!=1:raise ValueError("non-scalar intensity; preserve original message only")
    meta=dict(seq=seq,header_stamp_ns=str(stamp),coordinate_frame=frame,height=height,width=width,fields=schema,
              point_step=step,row_step=row_step,is_bigendian=bool(big),is_dense=bool(dense),
              intensity_available="intensity" in names,wire_sha256=sha(msg))
    arrays.update(xyz=xyz,intensity=intensity,source_point_index=np.arange(len(xyz),dtype=np.uint32),
        valid_mask=np.isfinite(xyz).all(1)&(xyz!=0).any(1),serialized_message=np.frombuffer(msg,np.uint8))
    return arrays,meta


def scan(msg):
    r=Cursor(msg);seq,stamp,frame=r.header();count=r.integer()
    if count<1 or len(msg)-r.pos!=count*1256:raise ValueError("not stamped 1248-byte legacy scan packets")
    return seq,stamp,frame,[(ns(r.take(8)),r.take(1248)) for _ in range(count)]


def pcd(path,arrays):
    mask=arrays["valid_mask"];xyz=arrays["xyz"][mask]
    dt=np.dtype([("x","<f4"),("y","<f4"),("z","<f4"),("intensity","<f4"),("source_point_index","<u4")])
    rows=np.empty(len(xyz),dt)
    for key,val in zip(("x","y","z"),xyz.T):rows[key]=val
    rows["intensity"]=arrays["intensity"][mask]
    rows["source_point_index"]=arrays["source_point_index"][mask]
    header=("VERSION .7\nFIELDS x y z intensity source_point_index\nSIZE 4 4 4 4 4\nTYPE F F F F U\nCOUNT 1 1 1 1 1\nWIDTH %d\nHEIGHT 1\nPOINTS %d\nDATA binary\n"%(len(xyz),len(xyz))).encode()
    with Path(path).open("xb") as out:out.write(header);out.write(rows.tobytes())
    return len(rows)
