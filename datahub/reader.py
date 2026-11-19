"""Portable native readers. Source and derived roots are supplied by the caller."""
import csv
import hashlib
import json
import os
from pathlib import Path

import numpy as np


SCHEMA = "strict_dust_native_v1"
DUSTX_CLASSES = dict(enumerate((
    "Ignore", "Ground", "Wall", "ArtificialWall", "Mountain", "Tree", "Grass",
    "VerticalObstacle", "StaticObstacle", "Dust", "Noise", "Rainwater", "Car",
    "Truck", "EngineeringVehicle", "Bus", "Pickup", "Pedestrian", "Rider",
    "Tricycle", "Bicycle", "Construction", "Trailer", "Wire", "Animal",
    "Unknown", "Stone", "Mound", "Panel")))
DUSTX_NON = frozenset(DUSTX_CLASSES) - {0, 9, 10, 11, 25}
EDITOR = {"pedestrian": 1, "vehicle": 2, "dust": 3, "static_boundary": 4}
PLY_TYPE = np.dtype([("x","<f4"),("y","<f4"),("z","<f4"),("intensity","<f4"),
                     ("original_index","<u4")])


def under(root, relative):
    base = Path(root).resolve(strict=True)
    ref = Path(relative)
    target = (base / ref).resolve(strict=True)
    if ref.is_absolute() or not target.is_relative_to(base):
        raise ValueError("source reference escapes its declared root")
    return target


def find_frame(derived_root, dataset_id, source_ref=None, *, uid=None):
    if source_ref is None and uid is None:
        raise ValueError("supply a source reference or a unique frame ID")
    base = Path(derived_root)
    sequences=[]
    for file in ("native_dataset_index.csv","bag_index.csv"):
        if (base/file).exists():
            with (base / file).open() as f:
                sequences.extend(csv.DictReader(f))
    match=None
    for seq in sequences:
        if seq["dataset_id"] != dataset_id or not seq.get("manifest_ref"):
            continue
        with under(base, seq["manifest_ref"]).open() as stream:
            for line in stream:
                row = json.loads(line)
                if ((uid is None or row["uid"]==uid)
                        and (source_ref is None or row["source_ref"] == source_ref)):
                    if uid is not None:
                        return row
                    if match is not None:
                        raise ValueError("multiple source messages match; supply an exact uid")
                    match=row
    if match is None:
        raise KeyError((dataset_id, source_ref,uid))
    return match


def past_window(rows, center_index, length):
    """Return verified ordinal context, oldest first. No implied physical dt."""
    if not 0 <= center_index < len(rows) or length < 1:
        raise ValueError("invalid center or window")
    if center_index + 1 < length:
        return []
    result = rows[center_index-length+1:center_index+1]
    center = result[-1]
    group = ("sequence_id", "event_group", "split", "sensor_id")
    if center.get("temporal_tier") != "STATIC_ORDER_ONLY" or any(
            any(r[k] != center[k] for k in group) or
            r["frame_order"] != center["frame_order"] - len(result) + i + 1
            for i,r in enumerate(result)):
        return []
    return result


def read_header(file, end, max_size=8192):
    lines = []
    while file.tell() < max_size:
        line = file.readline(max_size).decode("ascii").strip()
        if not line:
            raise ValueError("unterminated or empty binary cloud header")
        lines.append(line)
        if line.split()[0] == end:
            return lines
    raise ValueError("oversize header")


def pcd_header(stream):
    lines = read_header(stream, "DATA")
    meta = {p[0]:p[1:] for p in map(str.split,lines) if p[0] != "#"}
    if (meta["DATA"] != ["binary"] or meta["FIELDS"] != ["x","y","z","intensity"]
            or meta["SIZE"] != ["4"]*4 or meta["TYPE"] != ["F"]*4
            or meta["COUNT"] != ["1"]*4):
        raise ValueError("unreviewed PCD schema")
    n = int(meta["POINTS"][0])
    if n != int(meta["WIDTH"][0])*int(meta["HEIGHT"][0]):
        raise ValueError("PCD dimension mismatch")
    return n


def read_ply(path):
    with path.open("rb") as f:
        h = read_header(f,"end_header")
        props = [line for line in h if line.startswith("property ")]
        if h[:2] != ["ply","format binary_little_endian 1.0"] or props != [
                "property float x","property float y","property float z",
                "property float intensity","property uint original_index"]:
            raise ValueError("unreviewed PLY schema")
        n = int(next(line for line in h if line.startswith("element vertex ")).split()[2])
        data = np.fromfile(f,dtype=PLY_TYPE)
        if n != len(data):
            raise ValueError("PLY length mismatch")
    return data


def editor_codes(path, index, uid):
    doc = json.loads(path.read_text())
    if doc["frame_uid"] != uid:
        raise ValueError("editor frame identity mismatch")
    sort = np.argsort(index)
    sorted_index = index[sort]
    if np.any(sorted_index[1:] == sorted_index[:-1]):
        raise ValueError("duplicate POST-LIO original_index")
    code = np.zeros(len(index),np.uint8)
    owner = np.zeros(len(index),np.int32)
    conflicts = np.zeros(len(index),bool)
    identifiers = {}
    for annotation in doc["annotations"]:
        name = annotation["class_name"]
        label = EDITOR[name]
        identity = (name, annotation.get("instance_id",""))
        key = identifiers.setdefault(identity,len(identifiers)+1)
        ids = np.asarray(annotation["point_indices"],dtype=np.int64)
        if np.any(ids < 0):
            raise ValueError("negative source index")
        pos = np.searchsorted(sorted_index,ids)
        if np.any(pos >= len(index)) or not np.array_equal(sorted_index[pos],ids):
            raise ValueError("editor ID missing from PLY")
        local = sort[pos]
        conflicts[local] |= (owner[local] != 0) & (owner[local] != key)
        owner[local] = key
        code[local] = label
    code[conflicts] = 0
    return code, conflicts


def read_frame(row, data_root=None, valid_only=True, derived_root=None):
    """Return point-aligned arrays. stored_valid_mask always indexes stored rows.

    entity_type: 0 unspecified, 1 source person, 2 source motor vehicle.
    semantic_raw is None for sources without point labels. In quarantined
    semantic releases it retains the supplied IDs with zero supervision.
    """
    if row.get("eligibility") == "inventory_only":
        raise ValueError("inventory-only source has no registered frame reader")
    is_derived = row.get("point_ref_root") == "derived"
    root = (derived_root or os.environ.get("DERIVED_ROOT")) if is_derived else (
        data_root or os.environ.get("DATA_ROOT"))
    if not root:
        raise ValueError("set DATA_ROOT or DERIVED_ROOT for this source")
    path = under(root,row["point_ref"])
    fmt = row["format"]
    raw = conflicts = valid_external = box = None
    attrs = {}
    if fmt == "uchile_npy":
        xyz = np.load(path,allow_pickle=False)
        attrs["intensity"] = np.load(under(root,row["intensity_ref"]),allow_pickle=False).reshape(-1)
        raw = np.load(under(root,row["label_ref"]),allow_pickle=False).reshape(-1)
    elif fmt == "dustx_bin":
        points = np.fromfile(path,dtype="<f4").reshape(-1,4)
        xyz,attrs["intensity"] = points[:,:3],points[:,3]
        raw = np.fromfile(under(root,row["label_ref"]),dtype="u1")
    elif fmt == "post_lio_ply":
        data = read_ply(path)
        index = data["original_index"]
        if hashlib.sha256(index.astype("<u4",copy=False).tobytes()).hexdigest() != row["index_sha256"]:
            raise ValueError("PLY original_index identity mismatch")
        if len(index) and int(index.max()) >= row["source_cloud_points"]:
            raise ValueError("original_index outside POST-LIO message")
        xyz = np.column_stack([data[k] for k in ("x","y","z")])
        attrs["intensity"] = data["intensity"]
        raw,conflicts = editor_codes(under(root,row["label_ref"]),index,row["source_frame_uid"])
    elif fmt == "civil_pcd":
        with path.open("rb") as f:
            n = pcd_header(f)
            points = np.fromfile(f,dtype="<f4").reshape(n,4)
        xyz,attrs["intensity"] = points[:,:3],points[:,3]
        if row.get("box_ref"):
            box = json.loads(under(root,row["box_ref"]).read_text())
    elif fmt == "bag_npz":
        with np.load(path,allow_pickle=False) as z:
            xyz, index, valid_external = z["xyz"],z["source_point_index"],z["valid_mask"]
            attrs["intensity"] = z["intensity"]
            for field in row.get("details",{}).get("fields",[]):
                if field["name"] not in {"x","y","z","intensity"}:
                    attrs[field["name"]]=z[field["key"]]
            for key in ("ring","driver_timestamp_seconds","raw_distance_counts","raw_intensity","raw_block_return_byte"):
                if key in z and z[key].shape[:1]==(len(xyz),):
                    attrs[key] = z[key]
    else:
        raise ValueError("unknown source format")
    n = len(xyz)
    if xyz.shape != (n,3) or (row.get("stored_points") is not None and n != row["stored_points"]):
        raise ValueError("stored XYZ dimension mismatch")
    if fmt not in {"post_lio_ply","bag_npz"}:
        index = np.arange(n,dtype=np.uint32)
    if (raw is not None and len(raw)!=n) or any(len(a)!=n for a in attrs.values()) or index.shape!=(n,):
        raise ValueError("misaligned point arrays")
    valid = np.isfinite(xyz).all(axis=1)
    if row.get("exclude_zero_xyz"):
        valid &= np.any(xyz != 0,axis=1)
    if valid_external is not None:
        if valid_external.shape != (n,) or valid_external.dtype != bool:
            raise ValueError("invalid geometry mask")
        valid &= valid_external
    task = np.zeros(n,np.uint8)
    entity = np.zeros(n,np.uint8)
    if fmt == "uchile_npy":
        if not np.isin(raw,[0,1]).all():
            raise ValueError("undocumented UCHILE semantic ID")
        task[:] = np.where(raw==0,2,1)
    elif fmt == "dustx_bin" and row["raw_label_schema"]=="dustx_fine":
        if not np.isin(raw,list(DUSTX_CLASSES)).all():
            raise ValueError("undocumented fine semantic ID")
        task[np.isin(raw,list(DUSTX_NON))] = 1
        task[raw==9] = 2
        entity[raw==17] = 1
        entity[np.isin(raw,[12,13,14,15,16])] = 2
    elif fmt == "post_lio_ply":
        entity[raw==1] = 1
        entity[raw==2] = 2
        task[entity>0] = 1
        if row["medium"] == "dust":
            task[raw==3] = 2
    task[~valid]=0
    entity[~valid]=0
    sel = valid if valid_only else slice(None)
    available = {}
    for name,arr in attrs.items():
        finite = np.isfinite(arr[valid])
        values = arr[valid][finite]
        present=row.get("details",{}).get("intensity_available",True) if name=="intensity" else True
        available[name] = {"present":bool(present),
                           "finite_values":int(finite.sum()),
                           "constant":bool(len(values) and values.min()==values.max())}
    return dict(xyz=xyz[sel],attributes={k:v[sel] for k,v in attrs.items()},attribute_available=available,
                source_point_index=index[sel],stored_valid_mask=valid,valid_mask=valid[sel],
                semantic_raw=None if raw is None else raw[sel],semantic_source_schema=row["raw_label_schema"],
                task_label=task[sel],supervision_mask=task[sel]!=0,entity_type=entity[sel],
                conflict_mask=None if conflicts is None else conflicts[sel],frame_meta=row,boxes=box)
