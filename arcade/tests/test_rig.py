import json
import math
from pathlib import Path

import rig
from gen import rigs as gen_rigs

GOLDEN = Path(__file__).resolve().parent / "golden"


def test_golden_matches_reference():
    """tests/golden/ was written by tools/rig_build.py from python/rig.py; it must still agree."""
    for r in gen_rigs.RIGS.values():
        g = json.loads((GOLDEN / f"rig_{r['name']}.json").read_text())
        for a in r["anims"]:
            for k, phase in enumerate(g["phases"]):
                pose = rig.pose(r, a["id"], phase)
                for b, want in zip(r["bones"], g["anims"][a["name"]][k]):
                    got = pose[b["name"]][1]
                    assert max(abs(p - q) for p, q in zip(got, want)) < 1e-4, (r["name"], a["name"], phase)


def test_rotation_order_and_conventions():
    # Legs hang along -Y: rx < 0 swings the foot forward (+Z), rz > 0 towards +X (api.md §5.1).
    foot = (0.0, -1.0, 0.0)
    fwd = rig.apply((rig.rot(-90, 0, 0), (0, 0, 0)), foot)
    side = rig.apply((rig.rot(0, 0, 90), (0, 0, 0)), foot)
    assert fwd[2] > 0.99 and side[0] > 0.99
    # yaw first, then pitch: [rx, 90, 0] turns the pitched vector about world Y
    v = rig.apply((rig.rot(-90, 90, 0), (0, 0, 0)), foot)
    assert v[0] > 0.99


def test_loop_wraps_and_one_shot_ends():
    keys = [[0, 0, 0], [10, 0, 0], [20, 0, 0], [30, 0, 0]]
    assert rig.sample(keys, 0, True) == keys[0]
    assert abs(rig.sample(keys, 224, True)[0] - 15) < 1e-9  # halfway from the last key back to the first
    assert rig.sample(keys, 255, False) == [30.0, 0.0, 0.0]


def test_rider_sits_on_saddle():
    horse, rider = gen_rigs.RIGS[gen_rigs.HORSE], gen_rigs.RIGS[gen_rigs.PC]
    sx, sy, sz = rig.attach(horse, "saddle", "gallop", 0, 3.0, 0.0, 4.0, math.pi / 2)
    assert abs(sx - 2.95) < 1e-6 and abs(sz - 4.0) < 1e-6 and 1.6 < sy < 1.9  # 5 cm behind the centre
    hips = rig.pose(rider, "ride", 0)["root"][1]
    assert hips == tuple(rider["bones"][0]["offset"])
