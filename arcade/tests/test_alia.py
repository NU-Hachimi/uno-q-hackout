"""alia-engine poses Megalith's rigs in C++ (python/gen/rigs.apak). Its poses must match the golden files,
tests/golden/rig_<name>.json, which tools/rig_build.py writes from rig.py (the reference implementation):
every bone's rig-space transform, and every slot's position on a spawned rig."""

import json
from pathlib import Path

import assets
import world
from arena import ENGINE, W
from gen.rigs import RIGS

GOLDEN = Path(__file__).resolve().parent / "golden"
TOLERANCE = 2e-5  # float32 against Python's doubles, rounded to 5 decimals in the files


def points(m):
    """Origin and +X/+Y/+Z unit points of a row-major 3x4 transform, as in the golden files."""
    t = (m[3], m[7], m[11])
    return [*t] + [t[r] + m[4 * r + c] for c in range(3) for r in range(3)]


def test_engine_poses_match_the_golden_files():
    rigs = assets.load(ENGINE)
    worst = 0.0
    for ref in RIGS.values():
        golden = json.loads((GOLDEN / f"rig_{ref['name']}.json").read_text())
        mine = rigs[ref["name"]]
        assert mine.anims == [a["name"] for a in golden["anims"]]
        node = W.spawn_rig(mine)
        bones = len(ref["bones"])
        for anim in golden["anims"]:
            for phase, want in zip(golden["phases"], anim["poses"]):
                for m, w in zip(mine.pose(anim["id"], phase), want[:bones]):
                    worst = max(worst, max(abs(a - b) for a, b in zip(points(m), w)))
                node.animator.anim, node.animator.phase = anim["id"], phase
                for slot, w in enumerate(want[bones:]):
                    worst = max(worst, max(abs(a - b) for a, b in zip(node.slot(slot).world_position, w[:3])))
        node.destroy()
    assert worst < TOLERANCE, worst


def test_engine_ground_matches_terrain_height():
    scene = world.make_scene(1)
    world.set_ground(W, scene)
    for x in range(-130, 131, 7):
        for z in range(-130, 131, 11):
            assert abs(W.ground_height(x, z) - world.terrain_height(scene, x, z)) < 1e-4
