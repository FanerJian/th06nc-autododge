#!/usr/bin/env python3
"""
dds2png.py -- batch-convert DDS textures to PNG using Pillow.

Usage:
    python3 dds2png.py SRC_DIR DST_DIR [--workers N]

Mirrors the directory tree of SRC_DIR into DST_DIR, converting every
*.dds into a *.png next to its source (other files are copied as-is).

Example:
    python3 dds2png.py extracted preview_full --workers 8
"""

import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")


def convert_one(src, dst_dir):
    rel = os.path.relpath(src)
    out_dir = os.path.join(dst_dir, os.path.dirname(rel))
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(dst_dir, os.path.splitext(rel)[0] + ".png")
    try:
        im = Image.open(src)
        im.load()
        im.convert("RGBA").save(out)
        return rel, None
    except Exception as e:  # noqa: BLE001
        return rel, repr(e)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src_dir = sys.argv[1]
    dst_dir = sys.argv[2]
    workers = 4
    if "--workers" in sys.argv:
        workers = int(sys.argv[sys.argv.index("--workers") + 1])

    todo = []
    for root, _dirs, files in os.walk(src_dir):
        for f in files:
            if f.lower().endswith(".dds"):
                todo.append(os.path.join(root, f))
    print(f"converting {len(todo)} DDS files with {workers} workers...")

    done = ok = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(convert_one, s, dst_dir): s for s in todo}
        for fut in as_completed(futs):
            rel, err = fut.result()
            done += 1
            if err:
                print(f"FAIL {rel}: {err}")
            else:
                ok += 1
            if done % 200 == 0:
                print(f"... {done}/{len(todo)} done")
    print(f"finished: {ok}/{len(todo)} converted -> {dst_dir}")


if __name__ == "__main__":
    main()
