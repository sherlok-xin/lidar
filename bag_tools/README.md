# Bounded ROS1 LiDAR windows

`inventory.py` traverses a data root and reads ROS1 bag v2 footers to enumerate stored topics, native datatypes, message counts and recording spans. Source bags are opened read-only. The inventory distinguishes wire point clouds, complete packet scan messages, packet calibration and derived segmentation topics. A verified footer establishes the indexed message count. Only windows produced by the extractor have geometry validation. A sequence with two sensor streams does not have a combined unique frame count.

`extract_window.py` writes one directory per source identity and topic under the derived root. The input fingerprint covers the first 64 KiB, byte length and footer location. Each extracted original serialized message also receives a full SHA-256. `frame_uid` additionally includes the exact topic and message ordinal in physical bag record order. Header and record stamps use decimal nanosecond strings. The point cache retains all slots, the original message byte-for-byte, source integer point indices, a finite non-origin geometry mask, original intensity and its availability. Binary PCD previews show the valid subset with its original indices. Positive ranges with zero intensity remain eligible.

## Run

Use Python 3 with NumPy, plus Python lz4 for LZ4-compressed bags. Run from this source directory. Set `DATA_ROOT` to the read-only data and `DERIVED_ROOT` to a separate new output tree. Each `--source` is the path relative to `DATA_ROOT`. Only use source inputs you are authorized to decode.

```bash
mkdir -p "$DERIVED_ROOT"
python3 -m unittest -v test_readers
python3 extract_window.py --data-root "$DATA_ROOT" --derived-root "$DERIVED_ROOT" \
  --source "$PC2_SOURCE" --topic "$PC2_TOPIC" --kind pc2 --start 0 --take 3
```

The packet pilot supports the legacy stamped 1248-byte packet envelopes in the documented RS128 scan schema. The source must contain matching native scan and packet MD5s, RS-Ruby family byte, three 128-channel blocks and live 128-channel DIFOP calibration. Build the project-owned bridge against the unmodified upstream driver. `RS_DRIVER_ROOT` is the rs_driver repository root and `EIGEN_INCLUDE` contains the Eigen headers. The tested rs_driver revision is `897b14d3bdb6186a75df27ba51b65b5bd5557723`. Keep the installed driver and Eigen under their original licenses. [Upstream decoder](https://github.com/RoboSense-LiDAR/rs_driver/blob/897b14d3bdb6186a75df27ba51b65b5bd5557723/src/rs_driver/driver/decoder/decoder_RS128.hpp)

```bash
test "$(git -C "$RS_DRIVER_ROOT" rev-parse HEAD)" = 897b14d3bdb6186a75df27ba51b65b5bd5557723
g++ -O2 -std=c++14 -shared -fPIC -I"$RS_DRIVER_ROOT/src" -I"$EIGEN_INCLUDE" \
  rs128_bridge.cpp -o "$DERIVED_ROOT/rs128_bridge.so" -pthread
python3 extract_window.py --data-root "$DATA_ROOT" --derived-root "$DERIVED_ROOT" \
  --source "$RUBY_SOURCE" --topic "$RUBY_TOPIC" --kind ruby --start 0 --take 3 \
  --driver "$DERIVED_ROOT/rs128_bridge.so" --driver-commit 897b14d3bdb6186a75df27ba51b65b5bd5557723
python3 inventory.py --data-root "$DATA_ROOT" --derived-root "$DERIVED_ROOT"
python3 verify_window.py --data-root "$DATA_ROOT" --derived-root "$DERIVED_ROOT"
```

Each run uses an unused output location. Source v2 footers, supported compression, per-chunk length, a finite read budget and a maximum of 100 requested frames bound extraction. Packet scans are taken from the first requested ordinal whose previous DIFOP passed checks. An extraction error can leave partial files for inspection. A complete window has a validated `sequence.json` and `frames.jsonl`. The inventory can also take an authorized prior recording-manifest via `--event-manifest` to tie source names and sizes to known recording ancestry.

## Field and timing interpretation

- PointCloud2 uses the actual message height, width, row and point stride, endian flag, PointField datatypes, offsets and counts. All declared fields are retained, including vector fields. Arrays `field_0`, etc. are named by their schema in the corresponding frame JSON.
- RS-Ruby source slots enumerate packet, native block and hardware channel. Driver ring is stored as a separate calibrated attribute. Raw block return bytes are preserved without assigning per-point return identity. Decoded driver timestamps are floating-point sensor seconds and the raw embedded packet timestamp is retained as integer microseconds. Neither implies a clock offset correction, vehicle pose or extrinsic.
- The source scan envelope and native decoder coordinate frame are separately recorded. Decoded XYZ uses metres in the upstream driver frame. The sampler does not resplit ROS scan envelopes or transform them to vehicle/world coordinates.
- `verify_window.py` reopens the actual bags, checks source record locators, wire hashes, integer timestamps and original slots, independently re-parses all fields or calibrated hardware channels, checks ring order and vertical geometry against the source DIFOP, and verifies the binary PCD point-for-point.

## Verified pilot scope

| Representation | Frames | Stored slots | Geometrically valid | Valid with zero intensity |
|---|---:|---:|---:|---:|
| Standard organized PointCloud2 | 3 | 432,000 | 309,970 | 346 |
| Native RS128 packet scan | 3 | 691,200 | 312,331 | 509 |

The maximum independent calibrated vertical-coordinate difference was 0.00000121 m over the valid decoded slots. All 1,800 packet envelope times were zero in the chosen scan window. Embedded packet time and ROS header differed by approximately eight hours. Retain both clock domains. Geometry, packet counts and slot integrity passed on these windows. The data provide no corresponding material labels, verified motion transform or clock alignment.
