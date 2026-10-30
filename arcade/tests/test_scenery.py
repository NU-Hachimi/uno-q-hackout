import math

import g3d
import world
from arena import W
from gen import mesh_ids
from gen.looks import LOOKS


def test_rocks_stay_out_of_the_arena():
    scene = world.make_scene(seed=3)
    assert 0 < len(scene.rocks) <= 64
    kinds = {mesh_ids.ROCK_A, mesh_ids.ROCK_B, mesh_ids.PILLAR_BROKEN, mesh_ids.ARCH_FRAGMENT}
    for x, z, _, scale, mesh, tint in scene.rocks:
        assert math.hypot(x, z) > world.ARENA_RADIUS and mesh in kinds and tint == 0 and scale > 0
    assert world.make_scene(seed=3).rocks == scene.rocks


def test_every_time_of_day_uploads():
    for look in world.TIME_OF_DAY:
        scene = world.make_scene(seed=1, look=look)
        header, chunks, crc = g3d.pack_scene(scene)
        assert [len(d) for k, _, d in chunks if k == g3d.KIND_LOOK] == [76]
        assert header[1] == 1  # the moose
        assert scene.fog_far == 2 * LOOKS[look]["scene"].get("fog_far", scene.fog_far / 2)


def test_day_cycle_holds_each_look_then_blends():
    period = world.DAY_HOLD + world.DAY_BLEND
    for i, look in enumerate(world.TIME_OF_DAY):
        fields, block = world.sky_at(i * period + 1.0)
        assert block == LOOKS[look]["block"] and fields == world.sky_fields(look)
        nxt = world.TIME_OF_DAY[(i + 1) % len(world.TIME_OF_DAY)]
        _, end = world.sky_at(i * period + period - 1e-6)
        assert abs(end[64 + 1] - LOOKS[nxt]["block"][65]) <= 1  # saturation has reached the next look
    mid_fields, _ = world.sky_at(world.DAY_HOLD + world.DAY_BLEND / 2)
    a, b = world.sky_fields("forbidden_plain"), world.sky_fields("dusk")
    assert min(a["fog_far"], b["fog_far"]) <= mid_fields["fog_far"] <= max(a["fog_far"], b["fog_far"])
    assert len(g3d.pack_sky(*world.sky_at(3.0))) == 90


def test_sky_update_only_while_changing():
    from game import Game
    game = Game(world.make_scene(1), W)
    assert game.sky_update(0.05)  # first call always sends
    game.day = 1.0
    assert game.sky_update(1.0) is None  # still holding noon: nothing new
    game.day = world.DAY_HOLD + 2.0
    assert game.sky_update(1.0)
