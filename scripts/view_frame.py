#!/usr/bin/env python3
"""Generate bounded shared-view 3D PNG and offline interactive HTML."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opdf.visualization import render_frame


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('npz'); p.add_argument('--png', required=True); p.add_argument('--html')
    p.add_argument('--view', help='Version 1 shared camera JSON')
    p.add_argument('--max-points', type=int, default=30000)
    p.add_argument('--bbox', type=float, nargs=6, metavar=('XMIN','XMAX','YMIN','YMAX','ZMIN','ZMAX'))
    a = p.parse_args()
    print(json.dumps(render_frame(a.npz, output_png=a.png, output_html=a.html,
                    view=a.view, max_points=a.max_points, roi=a.bbox), indent=2))


if __name__ == '__main__':
    main()
