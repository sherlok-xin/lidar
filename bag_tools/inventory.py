"""ROS1 source inventory. Reads footer records, never individual bag chunks."""
import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path

from ros1_window import Bag, sha


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("x", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def scan_sources(data, derived, event_manifest=None):
    if not data.is_dir() or data == derived or data in derived.parents:
        raise ValueError("distinct data and derived roots required")
    failures = []
    paths = sorted(Path(directory) / f for directory, _, files in os.walk(
        data, onerror=lambda err: failures.append(str(err))) for f in files if f.lower().endswith(".bag"))
    samples = {s["source_ref"]: s for p in (derived/"sequences").glob("bag_*/sequence.json")
               for s in [json.loads(p.read_text())]}
    known = {}
    if event_manifest:
        for info in json.loads(event_manifest.read_text())["datasets"].values():
            name = Path(info["raw_bag"]).resolve()
            if data in name.parents:
                known[str(name.relative_to(data))] = (info["raw_size_bytes"], info["source_recording_uid"])
    rows, groups = [], []
    for path in paths:
        relative = str(path.relative_to(data))
        size = path.stat().st_size
        ancestry = known.get(relative)
        sample = samples.get(relative, {})
        inventory_bytes = 0
        topics, start, end, reason = [], None, None, ""
        try:
            with Bag(path, budget=32 << 20) as bag:
                totals = Counter()
                for _, counts in bag.chunks:
                    totals.update(counts)
                for key, c in sorted(bag.connections.items()):
                    role = ("prediction/derived_feature" if c["topic"].lower().endswith("/seg_points")
                            else "native_pointcloud" if c["type"] == "sensor_msgs/PointCloud2"
                            else "native_scan_packets" if c["type"] == "rslidar_msgs/rslidarScan"
                            else "packet_config" if c["type"] == "rslidar_msgs/rslidarPacket" else "metadata_only")
                    topics.append(dict(name=c["topic"], datatype=c["type"], messages=totals[key], role=role))
                if bag.chunk_times:
                    start = min(t[0] for t in bag.chunk_times)
                    end = max(t[1] for t in bag.chunk_times)
                identity = bag.identity
                inventory_bytes = bag.bytes
                state = "INDEX_VERIFIED_NO_PAYLOAD_CHECK"
        except (ValueError, OSError, EOFError, KeyError) as exc:
            reason = str(exc)
            with path.open("rb") as f:
                head = f.read(65536)
            identity = sha(b"header-only" + head + str(size).encode())
            state = "UNREADABLE_INDEX"
            inventory_bytes = len(head)
        group = sample.get("event_group") or (ancestry[1] if ancestry and ancestry[0]==size else "unknown:"+identity[:20])
        if sample and (identity!=sample["source_identity"] or state=="UNREADABLE_INDEX"):
            raise ValueError("bag no longer agrees with sampled source identity")
        seq = sample.get("sequence_id","bag_source_"+identity[:20])
        primary = [t for t in topics if t["role"] in {"native_scan_packets", "native_pointcloud"}]
        selected = [t for t in primary if t["name"]==sample.get("source_topic")]
        # Multiple native streams may cover the same physical scan. Never sum them as unique frames.
        source_frames = (selected[0]["messages"] if len(selected)==1 else
                         primary[0]["messages"] if len(primary)==1 else "")
        rows.append(dict(dataset_id="rosbag", sequence_id=seq, event_group=group, split="UNASSIGNED_UNLABELED",
                         source_ref=relative, format=sample.get("format","source_bag"),
                         frames=sample.get("frames",source_frames), stored_points=sample.get("stored_points",""),
                         valid_points=sample.get("valid_points",""), label_source="UNLABELED",
                         temporal_tier=sample.get("temporal_tier","UNAVAILABLE"),
                         eligibility=sample.get("eligibility","INVENTORY_ONLY"),
                         manifest_ref=("sequences/"+seq+"/frames.jsonl") if sample else "",
                         index_status=state, index_reason=reason, source_identity=identity, file_bytes=size,
                         index_bytes_read_scope="success=header/footer; failure=secondary fingerprint read",
                         index_bytes_read=inventory_bytes, record_min_ns=start, record_max_ns=end,
                         source_frames_single_stream=source_frames, sensor_streams=len(primary),
                         frames_scope="materialized-window" if sample else "single-native-stream-index-count",
                         topics_json=json.dumps(topics,ensure_ascii=False,separators=(",",":"))))
        evidence = ("recording ancestry from frozen label manifest and file size; no raw-to-label index binding"
                    if ancestry and ancestry[0]==size else "physical event unresolved; file identity for storage only")
        groups.append(dict(sequence_id=seq,event_group=group,evidence=evidence,split="UNASSIGNED_UNLABELED",
                           sensor_id="lidar1" if sample else "see topic inventory",independence_certified=False))
    if len({r["sequence_id"] for r in rows})!=len(rows):
        raise ValueError("duplicate source identity; resolve aliases before generating event groups")
    write_csv(derived/"bag_index.csv",rows)
    write_csv(derived/"bag_groups.csv",groups)
    summary=dict(files=len(rows),windows=len(samples),directories_unreadable=failures,
                 index_status=dict(Counter(r["index_status"] for r in rows)),bytes_index_or_fingerprint=sum(
                     r["index_bytes_read"] for r in rows),single_stream_count_unknown=sum(
                         r["source_frames_single_stream"]=="" for r in rows),
                 scan_scope="all .bag entries below DATA_ROOT; symlink directories not followed; no payload reads",
                 full_integrity_verified=False)
    (derived/"reports").mkdir(exist_ok=True)
    with (derived/"reports"/"bag_inventory_receipt.json").open("x") as out:
        json.dump(summary,out,ensure_ascii=False,indent=2)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root",type=Path,required=True)
    ap.add_argument("--derived-root",type=Path,required=True)
    ap.add_argument("--event-manifest",type=Path)
    opt=ap.parse_args()
    scan_sources(opt.data_root.resolve(),opt.derived_root.resolve(),opt.event_manifest)
