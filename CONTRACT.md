# OPDF-V1-B branch contract

All writes under /home/xin/lidar/opdf_v1. Source bag is /home/xin/lidar/data/2026-09-17-15-14-07_1.bag read-only. research_ops and integrated_dynamic_ws_v4.0 immutable. No production ROS/vehicle nodes. No GT/accuracy claims. New heuristic algorithm, not Phase3 or B1 comparison.

## Ownership

DATA-01 owns opdf/cloud_schema.py, opdf/io_rosbag.py, scripts/inspect_bag.py and tests/test_io*.py only. ALGO (PIPE-02) owns ground_lite.py, optical.py, geometry.py, decision.py and tests/test_algorithm*.py only. EVAL (RESEARCH-03) owns visualization.py, evaluation.py, scripts/view_frame.py, review_roi.py, publish_rviz.py, tests/test_evaluation*.py. MASTER owns configuration, pipeline.py, run_v1b.py, integration, docs. QA starts after implementation and real run, may write own tests/report. Cross-module dependencies through MASTER.

## FrameData (DATA implementation)

Dataclass fields: xyz float32/64 (N,3), intensity (N,), valid_xyz_mask bool(N,), raw_slot_id uint64(N,), height int, width int, point_step int, row_step int, header_stamp_ns int, record_stamp_ns int, frame_id str, source_bag str, source_record_locator dict, mapping_version str, source_fingerprint dict, field_schema list, is_bigendian bool, is_dense bool, raw_data bytes, phase_order ndarray(H,), column_coverage_mask bool(W,). N=H*W including invalid records. No invented physical missing columns: actual delivered W only; angular coverage UNKNOWN. raw_slot_id always original full slot order. Raw row padding remains raw_data, point bytes extracted stride-aware, not invented fields.

Methods: metadata()->JSON dict, to_image(values)->(H,W,...) using flat.reshape(W,H,...).transpose(...)[phase_order], from_image(image)->original flat inverse, point_bytes()->(N,point_step) uint8 exact original slot bytes. Schema rejects unsafe malformed fields/strides; dimensions can be empty or reduced W, pipeline ABSTAIN for wrong H/mapping.

IO: decode_pointcloud2(serialized, *, source_bag='', locator=None, record_stamp_ns=0, fingerprint=None, phase_order=None, mapping_version='phase2-candidate-v1')->FrameData. extract_frames(bag_path, output_dir, *, frames_per_window=3, max_frames=60, max_read_bytes=160*1024**2)->manifest dict; 3 windows first/middle/last from tail index, serialized .ros1msg cache under samples with JSON metadata. Manifest frames: path relative output_dir, key, seq, stamps, locator, sha256. load_cached_frame(path, metadata=None)->FrameData loads neighboring metadata/manifest provenance. CLI inspect/extract prints actual bytes/frames/elapsed. Must verify local bag, not blindly assume external copy offsets.

## Algorithm (ALGO implementation)

ground_lite.compute(frame, config), optical.compute(frame, config), geometry.compute(frame, config) return {'arrays':dict[str,np.ndarray], 'diagnostics':JSONdict}. Arrays are slot-aligned N or NxK; unavailable numeric values NaN, available bool. Keys for each score include *_available and reason_code bitmask. Available thresholds are debugging heuristics, never calibrated probabilities.

decision.classify(frame, ground, optical, geometry, config) same container, required arrays labels uint8(N,), score_e float32(N,), score_a float32(N,), available_e bool(N,), available_a bool(N,), reason_code uint32(N,). Enums INVALID=0,E=1,A=2,U=3,G=4. Module records its reason bit definitions. INVALID only invalid actual XYZ; MISSING represented metadata/coverage, never free. Ground retained separately. Protected solid=E+U; finite particles A candidates, not GT. Geometry unavailable/degenerate => no A based on missing evidence. Ground fit unreliable => no hard G; near-ground/low obstacles conservative U/protection.

config passed is complete config dict with ground/optical/geometry/decision subdicts; implementations select own block. Defaults must match configs/v1b.yaml. Add deterministic config seed and no global mutable algorithm state.

## Pipeline and outputs (MASTER)

pipeline.process_frame(frame, config, *, ablation='full')->{'arrays':flat slot arrays including labels/etc, 'diagnostics':dict, 'metadata':frame.metadata()}. NPZ includes xyz,intensity,valid_xyz_mask,raw_slot_id,labels,score_e,score_a,available_e,available_a,reason_code plus module arrays prefixed ground__/optical__/geometry__. .json metadata includes status,source fingerprint,raw message SHA,heuristic config hash,method version and modules timings. No raw data loss: original serialized message cache remains source; raw bytes invertible in FrameData.

outputs/<run_id>/frames/<key>.npz + <key>.json, config_snapshot.yaml, input_manifest.json, diagnostics.jsonl, metrics.csv, figures/<key>_3d.png (fixed camera four panels RAW/LABELS/A_ONLY/E_U), interactive/<key>.html, view.json. finite coordinates only displayed; no invalid fake points. Metrics behavior counts not precision/recall. Ablations ground / ground_optical / ground_geometry / full run same original slots. Sensitivity fixed predefined thresholds on small frames, no GT-optimal selection.

## EVAL API

visualization.render_frame(npz_path, *, output_png, output_html=None, view=None, max_points=30000, roi=None)->dict with paths/camera. Must real 3D, same selected raw IDs, crop and camera all panels. Use matplotlib mplot3d for fixed screenshots and a self-contained browser WebGL/Canvas 3D orbit viewer (no CDN) if Open3D absent. Prefer depth-projected actual xyz, interactive rotation/zoom with shared camera and raw slot inspect; no 2D fake. Label colors E cyan-green/A orange/U purple/G gray. A-only and E+U same view. Rendering cap deterministic raw index sample, explicitly not full point coverage.

evaluation.frame_metrics(npz_path, metadata=None)->dict of scalar behavior counters/range bands; evaluation.write_run_report(run_dir)->outputs metrics/automatic report without GT. review_roi supports exact original slots/bbox, evidence export, reviewer and confidence fields; no fabricated human annotations. Blind mode hides algorithm labels and no model-derived initial semantic answer. Case regression reruns source/config through pipeline and reports behavior changes, not accuracy.

ROS2 debug optional only /opdf_v1/raw,/solid,/aerosol_candidate,/unknown,/ground, original frame+stamp, explicit domain/localhost guard, no TF/control/planning. No DISPLAY means prepared script + limited self-check, never claim RViz visible.
