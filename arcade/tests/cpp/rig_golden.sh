#!/bin/sh
# Compare sketch/rig.cpp with the golden poses from python/rig.py (api.md §5.1): max error <= 1 cm.
#   sh tests/cpp/rig_golden.sh   (run from arcade/)
set -eu
cd "$(dirname "$0")/../.."
mkdir -p build/preview
g++ -std=gnu++17 -O2 -Wall -I sketch tests/cpp/rig_golden.cpp sketch/rig.cpp -o build/preview/rig_golden
build/preview/rig_golden > build/preview/rig_golden.json
python3 - <<'PY'
import json, sys
from pathlib import Path
cpp = {r["id"]: r["anims"] for r in json.load(open("build/preview/rig_golden.json"))["rigs"]}
worst, failed = 0.0, False
for path in sorted(Path("tests/golden").glob("rig_*.json")):
    gold = json.load(open(path))
    for anim, cpp_anim in zip(gold["anims"], cpp[gold["id"]]):
        for phase, want, got in zip(gold["phases"], anim["poses"], cpp_anim):
            err = max(abs(a - b) for w, g in zip(want, got) for a, b in zip(w, g))
            worst = max(worst, err)
            if err > 0.01:
                failed = True
                print(f"{path.name} {anim['name']} phase {phase}: max error {err:.4f} m")
print(f"rig golden: max error {worst * 1000:.3f} mm")
sys.exit(1 if failed else 0)
PY
