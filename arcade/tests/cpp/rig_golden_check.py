"""Compare rig_golden's stdout ("<rig_id> <anim> <phase> <bone> <x> <y> <z>") with tests/golden/rig_*.json."""
import json
import sys
from pathlib import Path

ARCADE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ARCADE / "python"))
from gen import rigs  # noqa: E402

TOLERANCE = 0.01  # m (api.md §5.1)

golden = {}
for r in rigs.RIGS.values():
    g = json.loads((ARCADE / "tests" / "golden" / f"rig_{r['name']}.json").read_text())
    for a in r["anims"]:
        for k, ph in enumerate(g["phases"]):
            for b, xyz in enumerate(g["anims"][a["name"]][k]):
                golden[(r["id"], a["id"], ph, b)] = xyz
seen, worst = 0, (0.0, (0, 0, 0, 0))
for line in sys.stdin:
    rid, a, ph, b, *xyz = line.split()
    key = (int(rid), int(a), int(ph), int(b))
    err = max(abs(float(c) - g) for c, g in zip(xyz, golden[key]))
    seen += 1
    worst = max(worst, (err, key))
if seen != len(golden):
    sys.exit(f"rig_golden: C++ printed {seen} bones, golden has {len(golden)}")
print(f"rig_golden: {seen} bone positions, worst error {worst[0] * 100:.4f} cm at {worst[1]}")
sys.exit(1 if worst[0] > TOLERANCE else 0)
