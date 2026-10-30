#!/usr/bin/env python3
"""Compare two tools/snapshot.py --alia runs, keyframe by keyframe:

    python3 tools/snapshot_compare.py OLD_DIR NEW_DIR

States (NAME.state.json): equal, or the first few fields that differ. Screenshots (NAME.alia.png): how many
pixels differ by more than 8 levels (and at all). Packets (NAME.frame): equal or not, while they still exist.
Exit 1 when any state or packet differs, or an image has pixels off by more than 8 levels.
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageChops


def flat(v, prefix=""):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from flat(x, f"{prefix}.{k}" if prefix else k)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from flat(x, f"{prefix}[{i}]")
        if not v:
            yield prefix, []
    else:
        yield prefix, v


def main():
    old, new = Path(sys.argv[1]), Path(sys.argv[2])
    bad = 0
    names = sorted(p.name.removesuffix(".state.json") for p in new.glob("*.state.json"))
    for name in names:
        notes = []
        a, b = old / f"{name}.state.json", new / f"{name}.state.json"
        if a.exists():
            fa, fb = dict(flat(json.loads(a.read_text()))), dict(flat(json.loads(b.read_text())))
            diff = [k for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)]
            if diff:
                bad += 1
                notes.append(f"state: {len(diff)} fields, e.g. " + ", ".join(f"{k} {fa.get(k)} -> {fb.get(k)}" for k in diff[:3]))
        else:
            notes.append("state: new")
        fa, fb = old / f"{name}.frame", new / f"{name}.frame"
        if fa.exists() and fb.exists() and fa.read_bytes() != fb.read_bytes():
            bad += 1
            notes.append("packet differs")
        ia, ib = old / f"{name}.alia.png", new / f"{name}.alia.png"
        if ia.exists() and ib.exists():
            r, g, b2 = ImageChops.difference(Image.open(ia).convert("RGB"), Image.open(ib).convert("RGB")).split()
            levels = ImageChops.lighter(ImageChops.lighter(r, g), b2).histogram()  # per pixel: its worst channel
            over, any_ = sum(levels[9:]), sum(levels[1:])
            if over:
                bad += 1
            if any_:
                notes.append(f"image: {over} px > 8 levels, {any_} px differ")
        if notes:
            print(f"{name}: " + "; ".join(notes))
    print(f"{len(names)} keyframes, {bad} differences that count")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
