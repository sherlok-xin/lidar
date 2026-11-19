"""Exact single-frame supervision and geometry-only causal history, protocol v1."""
import argparse
import csv
import os
import hashlib
import json
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
PUBLIC = (Path(os.environ.get("DATA_ROOT","datasets")).resolve() / "dataset_polvo")
LOCAL = (Path(os.environ.get("DATA_ROOT","datasets")).resolve() / "annotation_data")
OPS = Path(os.environ.get("HISTORICAL_ROOT","historical")).resolve()
ROLE = {"train": "train", "test": "test", "validation": "val",
        "exploratory_eval": "test", "purge": "purge"}
MANIFEST = ROOT / "manifest.json"
PACKAGE = {"ped": "original_pedestrian_dust", "follow": "high_speed_following_dust"}
SEED = "temporal-open3d-v1-20261119"


def sha_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def sha_file(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.sha256()
        for data in iter(lambda: stream.read(1 << 20), b""):
            digest.update(data)
    return digest.hexdigest()


def read_manifest(path=MANIFEST):
    path = Path(path)
    payload = path.read_bytes()
    if sha_bytes(payload) != Path(str(path) + ".sha256").read_text().split()[0]:
        raise ValueError("manifest receipt mismatch")
    return json.loads(payload)


def source_path(row):
    root = PUBLIC if row["domain"] == "uchile" else LOCAL
    path = (root / row["source"]).resolve()
    if root not in path.parents:
        raise ValueError("source escaped dataset")
    return path


def read_ply(path):
    dtype = np.dtype([(key, "<f4") for key in ("x", "y", "z", "intensity")] +
                     [("original_index", "<u4")])
    with path.open("rb") as stream:
        header = []
        for _ in range(64):
            line = stream.readline(500).decode("ascii").strip()
            if line == "end_header":
                break
            header.append(line)
        else:
            raise ValueError("PLY header")
        props = [line for line in header if line.startswith("property ")]
        if props != ["property float " + key for key in ("x","y","z","intensity")] + ["property uint original_index"] or "format binary_little_endian 1.0" not in header:
            raise ValueError("unsupported PLY layout")
        n = int(next(line.split()[-1] for line in header if line.startswith("element vertex ")))
        items = np.fromfile(stream, dtype=dtype, count=n)
        if len(items) != n or stream.read(1):
            raise ValueError("PLY length")
    return np.column_stack([items[key] for key in ("x","y","z")]), items["intensity"], items["original_index"]


def apply_source_labels(row, original_index, annotations, reviewed):
    order = np.argsort(original_index)
    sorted_indices = original_index[order]
    codes = np.zeros(len(order), np.uint8)
    instances = np.full(len(order), "", dtype=object)
    conflict = np.zeros(len(order), bool)
    for ann in annotations:
        if reviewed:
            identity = ann["source_frame_identity"]
            if identity["frame_uid"] != row["uid"] or identity["sensor_stamp_ns"] != row["sensor_stamp_ns"] or identity["recording_uid"] != row["event"] or not ann["human_reviewed"] or ann["review"]["decision"] != "accepted":
                raise ValueError("review binding mismatch")
            kind = ann["entity_kind"] if ann["label"] == "entity" else ann["label"]
            instance = ann.get("entity_uid", "") if ann["label"] == "entity" else ""
        else:
            kind = ann["class_name"]
            instance = ann.get("instance_id", "") if kind in ("vehicle","person","pedestrian") else ""
        code = {"person":1,"pedestrian":1,"vehicle":2,"dust":3,"static":4,"static_boundary":4}[kind]
        ids = np.asarray(ann["point_indices"])
        if not len(ids):
            continue
        if ids.dtype.kind not in "iu" or np.unique(ids).size != ids.size:
            raise ValueError("invalid label index")
        pos = np.searchsorted(sorted_indices, ids)
        if np.any(pos >= len(order)) or not np.array_equal(sorted_indices[pos], ids):
            raise ValueError("label index absent")
        positions = order[pos]
        conflict[positions] |= (codes[positions] != 0) & ((codes[positions] != code) | (instances[positions] != instance))
        codes[positions] = code
        instances[positions] = instance
    codes[conflict] = 0
    return codes, conflict


def load_frame(row, labels=True):
    if labels and row.get("context_only",False):
        raise ValueError("historical labels are unavailable to the feature path")
    path = source_path(row)
    if row["domain"] == "uchile":
        xyz = np.load(path/"coord.npy",allow_pickle=False)
        intensity = np.load(path/"intensity.npy",allow_pickle=False)
        original = np.arange(len(xyz),dtype=np.uint32)
    elif row["domain"] in PACKAGE:
        if row["processing_domain"] != "POST_LIO_CLOUD_BODY_IMU":
            raise ValueError("local processing domain")
        xyz, intensity, original = read_ply(path)
        if len(np.unique(original)) != len(original) or sha_bytes(original.astype("<u4").tobytes()) != row["index_sha256"]:
            raise ValueError("local source identity")
    else:
        raise ValueError("unknown domain")
    if xyz.shape != (len(intensity),3) or intensity.shape != (len(original),):
        raise ValueError("XYZI shape")
    valid = np.isfinite(xyz).all(axis=1) & np.isfinite(intensity)
    result = dict(xyz=np.ascontiguousarray(xyz,dtype=np.float32),intensity=np.ascontiguousarray(intensity,dtype=np.float32),original_index=np.ascontiguousarray(original),valid=valid)
    if not labels:
        return result
    if row["domain"] == "uchile":
        raw = np.load(path/"segment.npy",allow_pickle=False)
        if raw.shape != valid.shape or not np.isin(raw,[0,1]).all():
            raise ValueError("UCHILE labels")
        ref = np.where(raw == 0,3,5).astype(np.uint8)
        conflict = np.zeros(len(raw),bool)
    else:
        annotations = []
        if row["domain"] == "ped":
            with (LOCAL/row["label_path"]).open("rb") as stream:
                for offset, length, digest in row["label_spans"]:
                    stream.seek(offset)
                    data = stream.read(length)
                    if sha_bytes(data) != digest:
                        raise ValueError("review segment checksum mismatch")
                    annotations.append(json.loads(data))
        else:
            label_path = LOCAL/row["label_path"]
            if sha_file(label_path) != row["label_sha256"]:
                raise ValueError("editor digest")
            label = json.loads(label_path.read_bytes())
            if label["frame_uid"] != row["uid"] or label["sensor_stamp_ns"] != row["sensor_stamp_ns"]:
                raise ValueError("editor binding")
            annotations = label["annotations"]
        raw, conflict = apply_source_labels(row, original, annotations, row["domain"]=="ped")
        ref = raw.copy()
    code = np.zeros(len(ref),np.uint8)
    code[(ref==1)|(ref==2)|(ref==5)] = 1
    code[ref==3] = 2
    code[~valid|conflict] = 0
    result.update(code=code,ref=ref,source_code=raw,conflict=conflict)
    return result


def rank(uid):
    return sha_bytes((SEED+"|"+uid).encode())


def distributed_sample(rows, cap):
    if len(rows) <= cap:
        return list(rows)
    return [min((rows[int(j)] for j in bucket),key=lambda frame:rank(frame["uid"])) for bucket in np.array_split(np.arange(len(rows)),cap)]


def public_desc(meta, role):
    return dict(uid=meta["relative"].replace("/","__"),domain="uchile",event=meta["recording"],role=role,
                ordinal=int(meta["relative"].rsplit("_",1)[1]),source=meta["relative"],context_only=True)


@lru_cache(maxsize=55)
def signature(source):
    from scipy.spatial import cKDTree
    xyz = np.load(PUBLIC/source/"coord.npy",mmap_mode="r",allow_pickle=False)
    idx = np.random.default_rng(20261119).choice(len(xyz),min(len(xyz),4096),replace=False)
    cloud = xyz[idx]
    cloud = cloud[np.isfinite(cloud).all(axis=1)]
    return cloud,cKDTree(cloud)


def overlap(left,right):
    cloud,tree=signature(left["source"])
    prior,prior_tree=signature(right["source"])
    if min(len(cloud),len(prior))<256:
        return 0.
    return float(min((prior_tree.query(cloud[:512])[0]<=.35).mean(),(tree.query(prior[:512])[0]<=.35).mean()))


def window(current, candidates):
    history = []
    scores = []
    recent = current
    for past in reversed(candidates):
        if recent["ordinal"] != past["ordinal"]+1 or recent["role"] != past["role"] or recent["event"] != past["event"]:
            break
        measured = overlap(recent,past)
        scores.append(measured)
        if measured < .60:
            break
        history.append(past)
        recent = past
    return list(reversed(history)), scores


def frame_budget_local(frames, role, domain):
    if domain == "follow" and role != "test":
        return []
    return distributed_sample(frames,24 if role=="train" else 12)


def jsonl(path):
    return [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def build(path):
    public_file = OPS/"dust_learning_pilot/manifests/public_all_frames.json"
    local_file = OPS/"dust_learning_phase4/manifests/frame_manifest.json"
    split_file = OPS/"dust_learning_phase4/manifests/split.json"
    duplicate_file = OPS/"dust_learning_pilot/manifests/exact_cloud_duplicates.json"
    public = json.loads(public_file.read_bytes())
    old_frames = json.loads(local_file.read_bytes())["frames"]
    split = json.loads(split_file.read_bytes())
    if json.loads(duplicate_file.read_bytes()):
        raise ValueError("review exact duplicate clusters before freezing")
    groups = defaultdict(list)
    counts = defaultdict(Counter)
    used = []
    sources = [public_file,local_file,split_file,duplicate_file]
    for meta in public:
        role = ROLE[split["public_recording_roles"][meta["recording"]]]
        if role != ROLE[meta["split"]]:
            raise ValueError("split changed")
        row = public_desc(meta,role)
        groups[row["event"]].append((row,meta))
        counts[("uchile",role,"all")].update(frames=1,points=meta["source_points"],dust=meta["dust"],non_dust=meta["non_dust"],excluded=meta["invalid"])
    for event, pairs in sorted(groups.items()):
        pairs.sort(key=lambda pair:pair[0]["ordinal"])
        rows = [pair[0] for pair in pairs]
        if any(r["ordinal"]!=rows[0]["ordinal"]+index for index,r in enumerate(rows)):
            raise ValueError("recording gap")
        if len(set(tuple(meta["source_sha256"][:2]) for _,meta in pairs)) != len(rows):
            raise ValueError("repeated cloud in recording")
        for selected in distributed_sample(rows,8 if rows[0]["role"]=="train" else 4):
            pos = selected["ordinal"]-rows[0]["ordinal"]
            row = dict(selected,context_only=False)
            meta = pairs[pos][1]
            static = not event.startswith("caren/")
            hist,checks = window(row,rows[max(0,pos-9):pos]) if static else ([],[])
            distant = []
            if static and pos >= 36:
                old = rows[pos-27]
                prior, _ = window(old,rows[pos-35:pos-27])
                if len(prior)==8 and overlap(row,old)>=.60:
                    distant = prior + [old]
            row.update(history=hist,distant_history=distant,history_overlap_newest_first=checks,temporal_status=("T0" if hist else "HISTORY_INSUFFICIENT") if static else "T1_UNAVAILABLE",
                sensor="Ouster OS0 family",session=meta["atomic_group"],processing_domain="PUBLIC_PROCESSED_XYZI",
                frame_id="uchile_processed",sensor_stamp_ns=None,time_status="ordinal_only" if static else "odom_association_not_cloud_stamp",pose_status="fixed_reported_coordinate_overlap_screen" if static else "transformation_and_causality_unverified",
                index_domain="processed_NPY_row",label_source="publisher segment.npy",label_validity="PUBLISHER_POINT_LABEL",
                source_sha256=meta["source_sha256"],counts=dict(points=meta["source_points"],dust=meta["dust"],non_dust=meta["non_dust"],excluded=meta["invalid"]))
            counts[("uchile",row["role"],"selected")].update(frames=1,**row["counts"])
            used.append(row)
    review_rel = os.environ["REVIEWED_LABEL_REL"]
    receipt_path = LOCAL/os.environ["REVIEWED_RECEIPT_REL"]
    sources.append(receipt_path)
    review_path = LOCAL/review_rel
    if sha_file(review_path) != json.loads(receipt_path.read_bytes())["derived_labels_sha256"]:
        raise ValueError("reviewed file digest")
    spans = defaultdict(list)
    with review_path.open("rb") as stream:
        while True:
            offset=stream.tell()
            line=stream.readline()
            if not line: break
            ann=json.loads(line)
            spans[ann["source_frame_identity"]["frame_uid"]].append([offset,len(line),sha_bytes(line)])
    registry = {}
    for directory in sorted((LOCAL/"difficult_scenes_v2").iterdir()):
        package_file = directory/"package_manifest.json"
        if not package_file.is_file():
            continue
        package = json.loads(package_file.read_bytes())
        frames = jsonl(directory/"frames.jsonl")
        registry[directory.name] = {key:package.get(key) for key in ("dataset","recording_uid","source_bag_basename","exported_frames","cloud_topic","coordinate_contract","annotation_range_m")}
        registry[directory.name]["frame_ids_read"] = len(frames)
        registry[directory.name]["status"] = "registry_only_no_point_supervision_this_protocol"
        sources.extend((package_file,directory/"frames.jsonl"))
        if directory.name not in PACKAGE.values():
            continue
        domain=next(k for k,v in PACKAGE.items() if v==directory.name)
        registry[directory.name]["status"]="single_frame_entity_risk_only" if domain=="follow" else "single_frame_adaptation_and_entity_risk"
        lookup={frame["frame_uid"]:frame for frame in frames}
        roles=defaultdict(list)
        for meta in (item for item in old_frames if item["domain"]==directory.name):
            uid=meta["frame_uid"]
            frame=lookup[uid]
            if frame["cloud_topic"]!="/lio/cloud_body" or frame["cloud_frame_id"]!="imu" or frame["point_index_space"]!="lio_cloud_body_original_index" or frame["sensor_stamp_ns"]!=meta["sensor_stamp_ns"]:
                raise ValueError("POST-LIO identity")
            role=ROLE[meta["role"]]
            row=dict(uid=uid,domain=domain,event=frame["recording_uid"],session="independence_unverified",role=role,ordinal=frame["sequence_index"],source=str(Path(meta["source_ply"]).relative_to(LOCAL)),sensor="local_sensor_model_unverified",
                     processing_domain="POST_LIO_CLOUD_BODY_IMU",frame_id="imu",sensor_stamp_ns=frame["sensor_stamp_ns"],relative_sec=frame["relative_sec"],time_status="sparse_exact_sensor_stamp",pose_status="no_validated_continuous_POST_LIO_context",index_domain=frame["point_index_space"],index_sha256=frame["original_index_sha256"],source_sha256=meta["source_sha256"],label_source="rebound_declared_completed" if domain=="ped" else "editor_source_proxy",
                     label_validity="SOURCE_LABEL_PROXY_EXPLORATORY",context_only=False,history=[],distant_history=[],temporal_status="T1_UNAVAILABLE",
                     counts=meta["current_source_counts"])
            if domain=="ped":
                row.update(label_path=review_rel,label_spans=spans.get(uid,[]))
            else:
                row.update(label_path=str(Path(meta["editor_annotation"]).relative_to(LOCAL)),label_sha256=meta["editor_sha256"])
            roles[role].append(row)
            counts[(domain,role,"all")].update(frames=1,**row["counts"])
        for role in ("train","val","test"):
            for row in frame_budget_local(sorted(roles[role],key=lambda frame:frame["ordinal"]),role,domain):
                counts[(domain,role,"selected")].update(frames=1,**row["counts"])
                used.append(row)
    if len({row["uid"] for row in used})!=len(used):
        raise ValueError("duplicate center ID")
    for row in used:
        for past in row["history"]+row["distant_history"]:
            if past["ordinal"]>=row["ordinal"] or past["event"]!=row["event"] or past["role"]!=row["role"] or not past["context_only"]:
                raise ValueError("history leakage")
    manifest=dict(protocol="temporal_open3d_v1",selection="seeded one per ordinal stratum; disjoint source roles; label blind",seed=SEED,frames=used,role_counts={"|".join(key):value for key,value in sorted(counts.items())},annotation_registry=registry,
                  sources_sha256={str(item):sha_file(item) for item in sources},source_review_sha256=sha_file(review_path),
                  scope="UCHILE recording holdout; local same-event exposed exploratory blocks; no physical instance identities",
                  t0_gate="ordinal contiguous; publisher fixed setup; minimum symmetric support >=0.60 within 0.35 native units from deterministic geometry-only samples (4096 reference,512 queries); no original clock, labels, diff/flow or state fitted")
    payload=(json.dumps(manifest,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n").encode()
    if path.exists() and path.read_bytes()!=payload:
        raise FileExistsError("refusing to replace different frozen manifest")
    if not path.exists():
        with path.open("xb") as stream:stream.write(payload)
    checksum=Path(str(path)+".sha256")
    if not checksum.exists():
        with checksum.open("x") as stream:stream.write(sha_bytes(payload)+"  "+path.name+"\n")
    read_manifest(path)
    print(json.dumps(dict(centers=len(used),T0=sum(bool(row["history"]) for row in used),sha256=sha_bytes(payload),roles=manifest["role_counts"]),ensure_ascii=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--build",type=Path,required=True)
    build(parser.parse_args().build)
