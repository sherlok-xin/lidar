#!/usr/bin/env python3
"""Inspect a real local ROS1 finalized index, optionally extract bounded raw frames."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import json
from opdf.io_rosbag import extract_frames, inspect_bag, PROJECT_ROOT


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('bag', nargs='?', default='/home/xin/lidar/data/2026-09-17-15-14-07_1.bag')
    p.add_argument('--extract', action='store_true')
    p.add_argument('--output-dir', default=str(PROJECT_ROOT))
    p.add_argument('--frames-per-window', type=int, default=3)
    p.add_argument('--max-frames', type=int, default=60)
    p.add_argument('--max-read-mib', type=int, default=160)
    a = p.parse_args()
    if a.extract:
        result = extract_frames(a.bag, a.output_dir, frames_per_window=a.frames_per_window,
                                max_frames=a.max_frames, max_read_bytes=a.max_read_mib * 1024**2)
        print(json.dumps({k: result[k] for k in ('status', 'manifest_path', 'actual_bytes_read',
                                               'chunk_payload_bytes_read', 'elapsed_seconds')}
                         | {'frames': len(result['frames'])}, indent=2))
    else:
        print(json.dumps(inspect_bag(a.bag, max_read_bytes=a.max_read_mib * 1024**2), indent=2))


if __name__ == '__main__': main()
