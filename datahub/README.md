# Native LiDAR dataset interface

The hub references native arrays, binary points, sparse editor selections and civilian PCD frames. Set `DATA_ROOT` to the local dataset directory and `DERIVED_ROOT` to the generated hub. Source manifests containing filenames, clocks and acquisition identifiers stay local.

```python
import csv, json, os
from pathlib import Path
from datahub import read_frame
hub = Path(os.environ["DERIVED_ROOT"])
with (hub / "native_dataset_index.csv").open() as f:
    seq = next(r for r in csv.DictReader(f) if r["dataset_id"] == "uchile" and r["split"] == "train")
with (hub / seq["manifest_ref"]).open() as f:
    row = json.loads(next(f))
frame = read_frame(row)
print(row["uid"], frame["xyz"].shape, frame["source_point_index"].dtype)
```

Each row records the sensor, event group, source references, time provenance, processing domain, point identity, masks, and frozen or proposed split. Missing times remain null. Nanosecond strings preserve integer precision in JSON clients. To fetch an explicitly chosen UCHILE directory use `find_frame(hub, "uchile", relative_directory)`.

`read_frame(row, valid_only=False)` returns stored rows and a same-sized geometry mask. The default selects valid rows synchronously across attributes, semantic codes and integer source IDs. `stored_valid_mask` always indexes the full stored source. `semantic_raw=None` means that point labels are absent. `supervision_mask` selects the usable labelled points. A constant-zero intensity channel retains its actual values and availability diagnostics. Serialized ROS messages and packet-level timing remain in the original per-frame archive.

The strict dust mapping is in [label_schema.yaml](label_schema.yaml). Native PLY indices refer to the complete undistorted POST-LIO source message. `frame_meta["old_phase4_role"]` preserves earlier development exposure. A date-clustered `proposed_*` assignment is available for fine-schema DustX. A sequence with contradictory clock evidence is held together with its entire connected group. Static UCHILE ordinal windows from `past_window` require matching sequence, sensor, split, event, and consecutive ordinals. Mobile correspondence has to be verified separately.

To rebuild the private manifests or exercise the real-data checks from the package's parent:

```bash
python3 -B -m datahub.build --config "$NATIVE_PATH_CONFIG"
python3 -B -m datahub.check --bag-root "$DERIVED_ROOT" --report "$DERIVED_ROOT/reports/native_checks.json"
```

The [example path configuration](native_paths.example.json) shows the fields for the previous UCHILE audit and split, DustX content audit, annotation lineage evidence and approved source inventories. Dataset roots, review and rebind paths are relative to `DATA_ROOT`; earlier audit paths may be absolute locally or relative to the invocation directory. Substitute actual values on a source machine. Ready-made manifests can be read using NumPy and the standard library. The builder writes a private frame-level manifest and sequence summary for each registered native sequence and keeps inventory-only sources out of the reader. The separate bag builder registers its extracted NPZs in the same schema.
