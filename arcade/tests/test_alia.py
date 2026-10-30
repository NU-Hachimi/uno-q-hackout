"""alia-engine evaluates Megalith's rigs in C++ (python/gen/rigs.apak); its poses must match rig.py, the
reference implementation. Skipped when alia_engine isn't importable (PYTHONPATH=<alia-engine build>)."""

import pytest

import rig
from gen.rigs import RIGS

ae = pytest.importorskip("alia_engine")

PACK = __import__("pathlib").Path(__file__).resolve().parents[1] / "python" / "gen" / "rigs.apak"
PHASES = (0, 1, 31, 64, 100, 128, 200, 254, 255)


def test_engine_poses_match_rig_py():
    engine = ae.Engine(headless=True)
    try:
        rigs = engine.load_rigs(str(PACK))
        assert set(rigs) == {r["name"] for r in RIGS.values()}
        worst = 0.0
        for ref in RIGS.values():
            mine = rigs[ref["name"]]
            assert mine.anims == [a["name"] for a in ref["anims"]]
            for anim in range(len(ref["anims"])):
                for phase in PHASES:
                    for m, (r, t) in zip(mine.pose(anim, phase), rig.pose(ref, anim, phase)):
                        expect = (*r[0], t[0], *r[1], t[1], *r[2], t[2])
                        worst = max(worst, max(abs(a - b) for a, b in zip(m, expect)))
        assert worst < 1e-5  # float32 against Python's doubles
    finally:
        engine.close()


def test_engine_ground_matches_terrain_height():
    import world
    from arena import W

    scene = world.make_scene(1)
    world.set_ground(W, scene)
    for x in range(-130, 131, 7):
        for z in range(-130, 131, 11):
            assert abs(W.ground_height(x, z) - world.terrain_height(scene, x, z)) < 1e-4
