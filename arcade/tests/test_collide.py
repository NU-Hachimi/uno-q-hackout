"""Megalith's collision categories on alia-engine's colliders (collide.py); the ray and shape maths are
the engine's and tested there."""

import math
import random

import assets
import collide
import world
from arena import W
from boss import Boss, pick_parts
from gen.rigs import RIGS


def make_boss(seed=1):
    scene = world.make_scene(1)
    scene.slot_variants = pick_parts(random.Random(seed))
    return Boss(scene, W, random.Random(seed))


def test_the_pack_tags_the_boss_colliders():
    boss = make_boss()
    colliders = boss.colliders()
    bodies = [c for c in colliders if c.kind == "body"]
    parts = [c for c in colliders if c.kind == "part"]
    assert len(bodies) == sum(len(b.get("colliders", [])) for b in boss.rig["bones"])
    assert sorted(c.slot for c in parts) == [s for s, v in enumerate(boss.variants) if v]
    assert all(c.bone == boss.rig["slots"][c.slot]["bone_index"] for c in parts)
    assert [c.bone for c in bodies] == sorted(c.bone for c in bodies)  # in the rig's order
    hookable = [(b, c.get("hookable", False)) for b, bone in enumerate(boss.rig["bones"]) for c in bone.get("colliders", [])]
    assert [(c.bone, c.hookable) for c in bodies] == hookable
    assert [c.kind for c in boss.hook_targets()] == ["hook", "hook"]


def test_the_pc_rigs_collide_with_nothing():
    for rig in RIGS.values():
        if rig["name"] != "moose":
            W.spawn_rig(assets.RIGS[rig["name"]], position=(0, 0, -5))
    assert not W.colliders(0xFFFFFFFF)  # the horse's and the rider's colliders are on no layer


def test_a_broken_part_stops_catching_shots():
    boss = make_boss()
    slot = boss.parts[0]
    part = next(c for c in boss.colliders() if c.slot == slot)
    eye = tuple(p + q for p, q in zip(part.centre(), (0.0, 0.0, -30.0)))
    d = (0.0, 0.0, 1.0)
    assert boss.ray_cast(eye, d, 60.0, layers=collide.PART).collider == part
    boss._break(slot)
    assert boss.ray_cast(eye, d, 60.0, layers=collide.PART) is None or boss.ray_cast(eye, d, 60.0).collider != part


def test_excluding_a_bone_skips_its_shapes_and_parts():
    boss = make_boss()
    part = next(c for c in boss.colliders() if c.kind == "part")
    o = tuple(p + q for p, q in zip(part.centre(), (25.0, 0.0, 0.0)))
    d = (-1.0, 0.0, 0.0)
    hit = boss.ray_cast(o, d, 50.0, exclude_bone=part.bone)
    assert hit is None or hit.collider.bone != part.bone


def test_push_out_of_a_circle():
    assert collide.push_out(5, 0, 0, 0, 1) == (5, 0)
    x, z = collide.push_out(0.5, 0, 0, 0, 1)
    assert abs(math.hypot(x, z) - 1) < 1e-9
