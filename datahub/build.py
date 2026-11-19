"""Build a private, reference-only native index using a local path configuration."""
import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .reader import DUSTX_CLASSES, DUSTX_NON, SCHEMA, pcd_header, under


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(1<<20),b""):
            h.update(block)
    return h.hexdigest()


def jlines(path):
    with Path(path).open() as f:
        yield from (json.loads(x) for x in f)


def publish(path, content):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp = path.with_name("."+path.name+"."+str(os.getpid())+".tmp")
    with tmp.open("x",encoding="utf8") as f:
        f.write(content)
    os.replace(tmp,path)


def dump(path,value):
    publish(path,json.dumps(value,ensure_ascii=False,indent=2)+"\n")


def table(path, rows):
    from io import StringIO
    content=StringIO()
    writer=csv.DictWriter(content,fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
    writer.writeheader()
    writer.writerows(rows)
    publish(path,content.getvalue())


class Index:
    def __init__(self, root, out, cfg):
        self.root,self.out,self.cfg=root,out,cfg
        self.seqs,self.groups,self.splits=[],[],[]
        self.totals=defaultdict(Counter)
        self.sensors=[]

    def base(self, dataset, seq, event, sensor, fmt, source, order, n):
        uid = dataset+"_"+digest(seq+"|"+sensor+"|"+source)
        return dict(dataset_id=dataset,sequence_id=seq,event_group=event,event_group_id=event,sensor_id=sensor,
                    uid=uid,frame_uid=uid,frame_order=order,source_ref=source,format=fmt,
                    point_ref_root="data",source_topic=None,source_message_ordinal=None,
                    header_stamp_ns=None,bag_record_stamp_ns=None,stamp_ns=None,
                    timestamp_source="unavailable",clock_status="unknown",stored_points=n,valid_points=None,
                    point_count_stored=n,point_count_valid=None,point_ref=None,label_ref=None,
                    box_ref=None,camera_ref=None,pose_ref=None,calibration_ref=None,
                    pose_status="unavailable",calibration_status="unavailable",coordinate_frame="unknown",
                    units="unconfirmed",schema_version=SCHEMA,medium="dust",
                    temporal_tier="TEMPORAL_UNAVAILABLE",split="unassigned",eligibility="point_supervision")

    def sequence(self, rows, source, evidence, extra=None):
        r=rows[0]
        sequence=r["sequence_id"]
        if any(x["sequence_id"]!=sequence for x in rows):
            raise ValueError("mixed sequence")
        orders=[x["frame_order"] for x in rows]
        if len(set(x["uid"] for x in rows))!=len(rows):
            raise ValueError("duplicate frame identity")
        rows.sort(key=lambda x:(x["frame_order"],x["uid"]))
        clocks=Counter(x["stamp_ns"] for x in rows if x["stamp_ns"] is not None)
        for i,x in enumerate(rows):
            x["point_count_valid"]=x["valid_points"]
            x["duplicate_stamp"]=x["stamp_ns"] is not None and clocks[x["stamp_ns"]]>1
            self.splits.append({k:x[k] for k in ("dataset_id","sequence_id","uid","event_group","split","eligibility")})
        ref="sequences/"+sequence+"/frames.jsonl"
        publish(self.out/ref,"".join(json.dumps(x,separators=(",",":"),ensure_ascii=False)+"\n" for x in rows))
        roles=sorted(set(x["split"] for x in rows))
        stat=dict(dataset_id=r["dataset_id"],sequence_id=sequence,event_group=r["event_group"],
                  split="/".join(roles),source_ref=source,format=r["format"],frames=len(rows),
                  stored_points=sum(x["stored_points"] for x in rows),
                  valid_points=None if any(x["valid_points"] is None for x in rows) else sum(x["valid_points"] for x in rows),
                  label_source=r["label_status"],temporal_tier=r["temporal_tier"],
                  eligibility=r["eligibility"],manifest_ref=ref)
        self.seqs.append(stat)
        group=dict(sequence_id=sequence,event_group=r["event_group"],evidence=evidence,
                   split=stat["split"],sensor_id=r["sensor_id"],independence_certified=False)
        self.groups.append(group)
        dump(self.out/"sequences"/sequence/"sequence.json",dict(stat,group=group,
             duplicate_order_rows=len(orders)-len(set(orders)),duplicate_clock_rows=sum(n for n in clocks.values() if n>1),
             missing_times=sum(x["stamp_ns"] is None for x in rows),details=extra or {}))

    def dustx(self):
        cfg=self.cfg["dustx"]
        audit=json.loads(Path(cfg["full_audit"]).read_text())
        source=under(self.root,cfg["root"])
        group_rows=defaultdict(list)
        days=defaultdict(set)
        legacy={"ls128","ls64","ly150","ly300","m1","ouster"}
        # Share the largest plausible collection unit across sensors. Date tokens
        # in the new release and synthetic/implausible clocks remain unassigned.
        for group in audit["groups"]:
            sensor=group["folder"]
            fine=sensor in legacy
            sub=source/sensor
            if group["errors"] or len(group["per_frame"])!=len(list(sub.glob("*.bin"))):
                raise ValueError("DustX release changed or has audit errors")
            anomalies=defaultdict(list)
            for item in group["invalid_boxes"]:
                anomalies[item["frame"]].append(item["line"])
            stored=Counter({int(k):v for k,v in group["label_points"].items()})
            rejected=Counter({int(k):v for k,v in group["bad_xyz_labels"].items()})
            zeros=Counter({int(k):v for k,v in group["zero_xyz_labels"].items()})
            if fine and set(stored)-set(DUSTX_CLASSES):
                raise ValueError("new fine label requires review")
            checked_zero=0
            for f in group["per_frame"]:
                stem=f["stem"]
                n=f["n"]
                label=sub/(stem+".label")
                cloud=sub/(stem+".bin")
                bbox=sub/(stem+".txt")
                if cloud.stat().st_size!=16*n or label.stat().st_size!=n or not bbox.is_file():
                    raise ValueError("DustX pairing/byte size mismatch")
                if fine:
                    m=re.fullmatch(r"sequence_(\d+)_(\w+)_(\d+)_(\d+)_(\d+)",stem)
                    if m is None:
                        raise ValueError("unknown fine frame naming")
                    rec,observed_sensor,order,sec,frac=m.groups()
                    if observed_sensor!=sensor:
                        raise ValueError("unexpected fine source identity")
                    stamp=str(int(sec)*10**9+int(frac.ljust(9,"0"))) if len(frac)<=9 else None
                    rec="sequence_"+rec
                    day=int(sec)//86400
                else:
                    m=re.search(r"(?:^|_)(\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d)_(\d+)_",stem)
                    if not m:
                        raise ValueError("unknown collection prefix")
                    rec=m.group(1)+"_"+m.group(2)
                    m=re.search(r"_frame_(?:[^_]+_)?(\d+)(?:_flat)?$|_\d+_(\d+)_[^_]+$",stem)
                    if not m:
                        raise ValueError("unparsed collection ordinal")
                    order=next(a for a in m.groups() if a)
                    stamp=None
                seq="dustx_"+digest(sensor+"|"+rec)
                if fine:
                    days[seq].add(day)
                src=str(cloud.relative_to(self.root))
                r=self.base("dustx",seq,"dustx_event_"+digest(rec),sensor,"dustx_bin",src,int(order),n)
                valid=n-f["bad"]
                # Earlier audit has per-frame nonfinite counts, but only per-sensor
                # zero totals. Only the affected sensors need a geometry rescan.
                if group["zero_xyz_points"]:
                    geom=np.fromfile(cloud,dtype="<f4").reshape(n,4)[:,:3]
                    zero_count=int((geom==0).all(axis=1).sum())
                    checked_zero+=zero_count
                    valid-=zero_count
                r.update(point_ref=src,label_ref=str(label.relative_to(self.root)),box_ref=str(bbox.relative_to(self.root)),
                         box_excluded_lines=anomalies[stem],valid_points=valid,stamp_ns=stamp,
                         timestamp_source="source_filename_candidate" if fine else "collection_prefix_and_frame_order",
                         clock_status=("uncertified_filename_clock" if stamp else "subnanosecond_source_token_unconverted") if fine else "unknown",
                         raw_label_schema="dustx_fine" if fine else "dustx_unresolved",
                         label_version="native_uint8",label_status="publisher_fine" if fine else "SCHEMA_UNRESOLVED",
                         eligibility="point_supervision" if fine else "schema_quarantine",collection_prefix=rec,
                         geometry_domain="publisher_sensor_native",source_point_index_domain="bin_slot",
                         exclude_zero_xyz=bool(group["zero_xyz_points"]),raw_counts=f["ids"])
                group_rows[seq].append(r)
            if checked_zero!=group["zero_xyz_points"]:
                raise ValueError("zero-placeholder audit and current source differ")
            valid_counts={k:stored[k]-rejected[k]-zeros[k] for k in stored}
            stat={"dataset":"dustx","sensor":sensor,"schema":"fine" if fine else "unresolved",
                  "frames":group["frames"],"stored_points":sum(stored.values()),"valid_points":sum(valid_counts.values()),
                  "invalid_nonfinite_by_raw":dict(rejected),"invalid_zero_by_raw":dict(zeros),
                  "stored_by_raw":dict(stored),"valid_by_raw":valid_counts,
                  "valid_strict_dust":valid_counts.get(9,0) if fine else None,
                  "valid_nondust":sum(valid_counts.get(k,0) for k in DUSTX_NON) if fine else None,
                  "intensity_range":group["intensity_range"],"all_zero_intensity_frames":group["all_zero_intensity_frames"],
                  "box_rows":group["box_rows"],"invalid_box_rows":len(group["invalid_boxes"]),"empty_box_files":group["empty_box_files"]}
            self.sensors.append(stat)
            self.totals["dustx_fine" if fine else "dustx_unresolved"].update({k:stat[k] for k in (
                       "frames","stored_points","valid_points","valid_strict_dust","valid_nondust") if stat[k] is not None})
        # Transitive union guards all sequences sharing any plausible date.
        parent={s:s for s in days}
        def root(s):
            while s!=parent[s]:
                parent[s]=parent[parent[s]]
                s=parent[s]
            return s
        seen={}
        for seq,ss in sorted(days.items()):
            for day in ss:
                peer=seen.setdefault(day,seq)
                a,b=root(seq),root(peer)
                parent[max(a,b)]=min(a,b)
        components=defaultdict(list)
        for seq in days:
            components[root(seq)].append(seq)
        for seq,rows in group_rows.items():
            provisional="unassigned_schema"
            if seq in days:
                comp=sorted(components[root(seq)])
                group="dustx_date_cluster_"+digest("|".join(comp))
                all_days={d for q in comp for d in days[q]}
                if min(all_days)<14610:  # dates before 2010 are suspect in these releases
                    provisional="unassigned_clock_review"
                else:
                    # Proposed only. No metric or fitted model is used in grouping.
                    split_bucket=int(digest(group)[:8],16)%10
                    provisional="proposed_"+("train" if split_bucket<7 else "validation" if split_bucket<9 else "test")
                for row in rows:
                    row["event_group"]=row["event_group_id"]=group
            for row in rows:
                row["split"]=provisional
            self.sequence(rows,rows[0]["collection_prefix"],
                       "entire publisher sequence joined transitively across sensors by any shared filename UTC day; unknown clocks held"
                       if seq in days else "matched collection date-time and run counter across sensors; semantic release on hold")

    def annotation(self):
        cfg=self.cfg["annotation"]
        native=under(self.root,cfg["root"])
        with Path(cfg["full_audit"]).open() as f:
            historical={(r["package"],r["frame_uid"]):r for r in csv.DictReader(f)}
        frozen=json.loads(Path(cfg["phase4"]).read_text())["frames"]
        roles={r["frame_uid"]:r["role"] for r in frozen if r["dataset"]=="local"}
        lineage=json.loads(Path(cfg["lineage"]).read_text())
        receipt=json.loads(under(self.root,cfg["rebind"]).read_text())
        reviewed_hash=file_hash(under(self.root,cfg["reviewed"]))
        if not (lineage["receipt_hashes_all_match"] and lineage["point_indices_identical_to_source_pending"]
                and reviewed_hash==receipt["derived_labels_sha256"]):
            raise ValueError("reviewed lineage receipt validation failed")
        review_flags=defaultdict(Counter)
        for record in jlines(under(self.root,cfg["reviewed"])):
            source_uid=record["source_frame_identity"]["frame_uid"]
            review_flags[source_uid].update(records=1,human_reviewed=int(record["human_reviewed"] is True),
                   accepted=int(record["review"].get("decision")=="accepted"))
        for name, (medium,status,eligibility) in cfg["groups"].items():
            path=native/name
            pkg=json.loads((path/"package_manifest.json").read_text())
            seq="annotation_"+digest("v2|"+pkg["recording_uid"])
            event=pkg["recording_uid"]
            rows=[]
            for f in jlines(path/"frames.jsonl"):
                uid=f["frame_uid"]
                n=f["exported_valid_point_count"]
                old=historical[(native.name+"/"+name,uid)]
                if int(old["exported_points"])!=n or old["cloud_topic"]!=f["cloud_topic"]:
                    raise ValueError("historical PLY count or source topic mismatch")
                ply=path/f["cloud_file"]
                label=path/"annotations"/(uid+".json")
                if not ply.is_file() or not label.is_file():
                    raise ValueError("annotation source missing")
                src=str(ply.relative_to(self.root))
                r=self.base("annotation",seq,event,"lidar1","post_lio_ply",src,
                            f["sequence_index"],n)
                stamp=str(f["sensor_stamp_ns"])
                counts={str(i):int(old[k+"_points"]) for i,k in enumerate(
                    ("unknown","pedestrian","vehicle","dust","static"))}
                if sum(counts.values())!=n:
                    raise ValueError("local audit denominator mismatch")
                r.update(point_ref=src,label_ref=str(label.relative_to(self.root)),raw_label_schema="editor_v2",
                         label_status=status,label_version="editor_v2",source_frame_uid=uid,
                         frame_uid="annotation_"+uid,uid="annotation_"+uid,medium=medium,
                         eligibility=eligibility,source_topic=f["cloud_topic"],source_message_ordinal=f["sequence_index"],
                         header_stamp_ns=stamp,stamp_ns=stamp,timestamp_source="source_cloud_sensor_stamp_ns",
                         clock_status="uncertified_absolute_epoch",coordinate_frame=f["cloud_frame_id"],units="metre_source_contract",
                         geometry_domain="undistorted_post_lio",source_point_index_domain=f["point_index_space"],
                         index_sha256=f["original_index_sha256"],source_cloud_points=f["cloud_point_count"],
                         valid_points=n,raw_counts=counts,conflict_points=int(old["conflict_points"]),
                         published_manifest_human_reviewed=f["human_reviewed"],package_formal_status=pkg["formal_metric_status"],
                         source_review_declared=False,old_phase4_role=roles.get(uid),editor_status="unknown",
                         split="inventory" if eligibility=="inventory_only" else roles.get(uid,"unassigned"))
                if eligibility!="inventory_only":
                    editor=json.loads(label.read_text())
                    if editor["frame_uid"]!=uid or editor["sensor_stamp_ns"]!=f["sensor_stamp_ns"] or old["editor_pending_same"]!="True":
                        raise ValueError("editor/source binding mismatch")
                    r["editor_status"]=editor.get("status")
                if status=="source_declared_reviewed":
                    entry=receipt["matches"][stamp]
                    if (entry["source_frame_uid"]!=uid or entry["editor_sha256"]!=file_hash(label)
                            or entry["ply_sha256"]!=file_hash(ply)):
                        raise ValueError("reviewed source digest mismatch")
                    r.update(source_review_declared=True,review_lineage_ref=cfg["reviewed"],
                             rebind_evidence_ref=cfg["rebind"],
                             reviewed_record_status_counts=dict(review_flags[uid]),
                             accepted_scope="source-declared completed export; independent material status unverified")
                if eligibility=="exploratory_single_frame":
                    r["split"]="historically_exposed_no_new_fit"
                rows.append(r)
            counts=Counter()
            for r in rows:
                counts.update(r["raw_counts"])
                if eligibility=="inventory_only":
                    r.update(point_ref=None,label_ref=None)
                    del r["raw_counts"]
            self.sequence(rows,str(path.relative_to(self.root)),
                         "metadata-bound POST-LIO recording; same-event historical time blocks retained in old_phase4_role",
                         dict(variant="v2",point_id="source message original_index",prior_variants="v1/pending and reviewed views excluded from duplicate counts",
                              historical_status=pkg["formal_metric_status"],source_proxy=status,
                              editor_status_counts=dict(Counter(x["editor_status"] for x in rows))))
            self.sensors.append(dict(dataset="annotation",sensor=seq,eligibility=eligibility,
                medium=medium,label_status=status,frames=len(rows),valid_points=sum(counts.values()),valid_by_raw=counts,
                source_cloud_slots=sum(x["source_cloud_points"] for x in rows),conflicts=sum(x["conflict_points"] for x in rows)))
            self.totals["annotation_"+eligibility].update(frames=len(rows),stored_points=sum(counts.values()),
                valid_points=sum(counts.values()),dust_source_slots=counts["3"] if medium=="dust" else 0,
                source_vehicle_slots=counts["2"],source_person_slots=counts["1"])

    def smoke(self):
        cfg=self.cfg["smoke"]
        src=under(self.root,cfg["root"])
        permit=cfg["admitted_civilian_sequence"]
        relation=src/cfg["evidence"]
        if not any(re.match(re.escape(permit)+r"\s",line) and "轿车" in line for line in relation.read_text().splitlines()):
            raise ValueError("documented civilian road sequence not identified")
        for path in sorted(x for x in src.iterdir() if x.is_dir() and x.name.isdecimal()):
            seq="smoke_"+digest(path.name)
            event="smoke_event_"+digest(path.name)
            lidar=path/"lidar"
            if path.name!=permit:
                n=sum(1 for _ in lidar.glob("*.pcd"))
                self.seqs.append(dict(dataset_id="smoke",sequence_id=seq,event_group=event,split="inventory",
                    source_ref=str(path.relative_to(self.root)),format="pcd_directory_inventory",frames=n,
                    stored_points=None,valid_points=None,label_source="inventory",temporal_tier="not_assessed",
                    eligibility="inventory_only",manifest_ref=None))
                self.groups.append(dict(sequence_id=seq,event_group=event,evidence="source directory inventory only",
                                        split="inventory",sensor_id="lidar1",independence_certified=False))
                self.totals["smoke_inventory"].update(frames=n)
                continue
            rows=[]
            bcount=Counter()
            pose=[str(p.relative_to(self.root)) for p in sorted((path/"pose").glob("*.csv"))]
            calibration=[str(p.relative_to(self.root)) for p in src.glob("*.ini")]
            for ordinal,cloud in enumerate(sorted(lidar.glob("*.pcd"))):
                with cloud.open("rb") as f:
                    n=pcd_header(f)
                    if f.tell()+16*n!=cloud.stat().st_size:
                        raise ValueError("unexpected binary PCD payload size")
                m=re.fullmatch(r"(\d+)\.(\d{1,9})",cloud.stem)
                if not m:
                    raise ValueError("unparsed civilian source time")
                ts=str(int(m.group(1))*10**9+int(m.group(2).ljust(9,"0")))
                img=path/"camera"/"front"/(cloud.stem+".jpg")
                box=path/"label"/(cloud.stem+".json")
                status="missing"
                n_box=None
                if box.exists():
                    box_data=json.loads(box.read_text())
                    if not isinstance(box_data,list):
                        raise ValueError("unrecognized civilian box document")
                    status="nonempty" if box_data else "empty"
                    n_box=len(box_data)
                    bcount["boxes"]+=n_box
                bcount[status]+=1
                ref=str(cloud.relative_to(self.root))
                r=self.base("smoke",seq,event,"lidar1","civil_pcd",ref,ordinal,n)
                r.update(point_ref=ref,raw_label_schema="no_point_labels",label_status="civilian_boxes_only",
                         label_version="source_box_json",medium="clear_road_by_source",
                         eligibility="box_review_only",split="single_event_no_independent_holdout",
                         geometry_domain="pcd_source_native",source_point_index_domain="pcd_storage_row",
                         timestamp_source="exact_decimal_filename",stamp_ns=ts,clock_status="uncertified_sensor_clock",
                         pose_status="source_tables_present_unaligned" if pose else "unavailable",
                         calibration_status="tables_present_applicability_unconfirmed" if calibration else "unavailable",
                         box_ref=str(box.relative_to(self.root)) if box.exists() else None,
                         camera_ref=str(img.relative_to(self.root)) if img.exists() else None,
                         box_file_state=status,source_annotation_completeness="unconfirmed",box_count=n_box)
                rows.append(r)
            self.sequence(rows,str(path.relative_to(self.root)),"one documented civilian road scene; no cross-frame object identity established",
                         dict(boxes=bcount,source_pose_tables=pose,source_calibration_candidates=calibration,
                              source_vehicle_type_string="retain as annotated; class string may be ambiguous"))
            self.totals["smoke_civilian"].update(frames=len(rows),stored_points=sum(r["stored_points"] for r in rows),
                                                  **bcount)

    def export(self):
        table(self.out/"native_dataset_index.csv", self.seqs)
        table(self.out/"native_sequence_groups.csv", self.groups)
        table(self.out/"splits"/"native_frames.csv", self.splits)

    def uchile(self):
        cfg=self.cfg["uchile"]
        native=under(self.root,cfg["root"])
        frames=json.loads(Path(cfg["frozen_manifest"]).read_text())
        details={r["relative_path"]:r for r in jlines(cfg["audit_frames"])}
        if len(details)!=len(frames):
            raise ValueError("frozen and audited UCHILE counts disagree")
        groups=defaultdict(list)
        for f in frames:
            src=f["relative"]
            a=details[src]
            n=f["source_points"]
            if n!=a["points"] or a["errors"]:
                raise ValueError("previous UCHILE audit failed")
            seq="uchile_"+digest(f["recording"])
            event="uchile_event_"+digest(f["atomic_group"])
            base=f"{cfg['root']}/{src}/"
            for name in ("coord.npy","intensity.npy","segment.npy"):
                if (native/src/name).stat().st_size!=a["fields"][name]["bytes"]:
                    raise ValueError("source size changed: "+src)
            r=self.base("uchile",seq,event,"lidar1","uchile_npy",src,a["frame_number"],n)
            r.update(split=f["split"],point_ref=base+"coord.npy",intensity_ref=base+"intensity.npy",
                     label_ref=base+"segment.npy",raw_label_schema="uchile_binary",label_status="publisher_point_labels",
                     label_version="published_segment_npy",valid_points=n-a["invalid_xyz"],
                     source_point_index_domain="coord_npy_row",geometry_domain="publisher_processed_native",
                     coordinate_frame="uchile_processed_axes_uncertified",coordinate_unit="source_unit_unverified",
                     temporal_tier="STATIC_ORDER_ONLY" if a["odom"] is None and f["subset"].lower().startswith(("interior","exterior")) else "TEMPORAL_UNAVAILABLE",
                     source_hashes=dict(zip(("point","intensity","label"),f["source_sha256"])),
                     raw_counts={"0":a["dust_0"],"1":a["non_dust_1"]},intensity_min=a["intensity_min"],intensity_max=a["intensity_max"])
            if a["odom"] is not None:
                r.update(pose_ref=base+"odom.npy",pose_status="stored_odometry_unaligned",
                         odom_source_float_seconds=repr(a["odom"]["timestamp"]))
            groups[f["recording"]].append(r)
        for rec,rows in groups.items():
            self.sequence(rows,rec,"frozen pilot atomic recording groups; physical session identity unconfirmed")
        self.totals["uchile"].update(frames=len(frames),stored_points=sum(f["source_points"] for f in frames),
                                    valid_points=sum(a["points"]-a["invalid_xyz"] for a in details.values()),
                                    dust_raw=sum(a["dust_0"] for a in details.values()),
                                    non_dust_raw=sum(a["non_dust_1"] for a in details.values()))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",required=True,type=Path)
    ap.add_argument("--sources",default="uchile,dustx,annotation,smoke")
    args=ap.parse_args()
    cfg=json.loads(args.config.read_text())
    idx=Index(Path(os.environ["DATA_ROOT"]).resolve(strict=True),Path(os.environ["DERIVED_ROOT"]),cfg)
    if idx.out.resolve().is_relative_to(idx.root):
        raise ValueError("derived output must be outside data root")
    existing=idx.out/"native_dataset_index.csv"
    if existing.is_file():
        with existing.open() as f:
            registered={r["dataset_id"] for r in csv.DictReader(f)}
        if registered-set(args.sources.split(",")):
            raise ValueError("partial rebuild would discard indexed sources; use a new output root")
    for name in args.sources.split(","):
        getattr(idx,name)()
        print(name,"completed",flush=True)
    idx.export()
    dump(idx.out/"reports"/"native_counts.json",dict(idx.totals))
    if idx.sensors:
        dump(idx.out/"reports"/"native_sensors.json",idx.sensors)


if __name__=="__main__":
    main()
