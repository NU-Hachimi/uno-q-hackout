import math

import terrain
from arena import W
from gen import mesh_ids
from gen.looks import LOOKS


def test_rocks_stay_out_of_the_arena():
    scene = terrain.make_scene(seed=3)
    assert 0 < len(scene.rocks) <= 64
    kinds = {mesh_ids.ROCK_A, mesh_ids.ROCK_B, mesh_ids.PILLAR_BROKEN, mesh_ids.ARCH_FRAGMENT}
    for x, z, _, scale, mesh, tint in scene.rocks:
        assert math.hypot(x, z) > terrain.ARENA_RADIUS and mesh in kinds and tint == 0 and scale > 0
    assert terrain.make_scene(seed=3).rocks == scene.rocks


def test_every_time_of_day_makes_a_scene():
    for look in terrain.TIME_OF_DAY:
        scene = terrain.make_scene(seed=1, look=look)
        assert len(scene.look) == 76 and scene.rig_id == 1  # the Look block look.py grades with; the moose
        assert scene.fog_far == 2 * LOOKS[look]["scene"].get("fog_far", scene.fog_far / 2)


def test_day_cycle_holds_each_look_then_blends():
    period = terrain.DAY_HOLD + terrain.DAY_BLEND
    for i, look in enumerate(terrain.TIME_OF_DAY):
        fields, block = terrain.sky_at(i * period + 1.0)
        assert block == LOOKS[look]["block"] and fields == terrain.sky_fields(look)
        nxt = terrain.TIME_OF_DAY[(i + 1) % len(terrain.TIME_OF_DAY)]
        _, end = terrain.sky_at(i * period + period - 1e-6)
        assert abs(end[64 + 1] - LOOKS[nxt]["block"][65]) <= 1  # saturation has reached the next look
    mid_fields, _ = terrain.sky_at(terrain.DAY_HOLD + terrain.DAY_BLEND / 2)
    a, b = terrain.sky_fields("forbidden_plain"), terrain.sky_fields("dusk")
    assert min(a["fog_far"], b["fog_far"]) <= mid_fields["fog_far"] <= max(a["fog_far"], b["fog_far"])


def test_sky_update_only_while_changing():
    from game import Game
    game = Game(terrain.make_scene(1), W)
    assert game.sky_update(0.05)  # first call always sends
    game.day = 1.0
    assert game.sky_update(1.0) is None  # still holding noon: nothing new
    game.day = terrain.DAY_HOLD + 2.0
    assert game.sky_update(1.0)
