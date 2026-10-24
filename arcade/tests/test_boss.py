import math
import random

import aim
import camera
import g3d
import world
import rig
from boss import KNEELING, STANDING, STRIKING, TURNING, Boss, pick_parts
from player import Player


def vantage(boss, slot, dist=20.0):
    """An eye position from which the part is the first thing a ray towards it hits."""
    import collide
    for elevation in (0.0, 35.0):
        for k in range(8):
            a, e = math.radians(45 * k), math.radians(elevation)
            c = next(c for c in boss.colliders() if c.slot == slot).centre()
            eye = (c[0] + dist * math.cos(e) * math.sin(a), c[1] + dist * math.sin(e), c[2] + dist * math.cos(e) * math.cos(a))
            d = tuple((q - p) / dist for p, q in zip(eye, c))
            hit = collide.ray_cast(eye, d, boss.colliders(), dist + 2)
            if hit and hit.collider.slot == slot:
                return eye
    raise AssertionError(f"part {slot} is not visible from anywhere")


def make_boss(seed=1):
    scene = world.make_scene(1)
    scene.slot_variants = pick_parts(random.Random(seed))
    return scene, Boss(scene)


def test_stands_still_until_it_attacks():
    scene, boss = make_boss()
    pc = Player(scene, x=20.0, z=0.0)  # to the side, 20 m: outside attack range
    yaw = boss.yaw
    for _ in range(200):
        boss.update(0.05, pc)
    assert boss.yaw == yaw and boss.state == STANDING and boss.anim == boss.anims["idle"]


def test_attack_turns_slowly_then_strikes_and_hurts():
    scene, boss = make_boss()
    pc = Player(scene, x=8.0, z=0.0)  # inside range, 90 degrees to the boss's left of facing
    boss.timer = 0.0
    boss.update(0.05, pc)
    assert boss.state == TURNING
    yaw = boss.yaw
    boss.update(0.5, pc)
    turned = abs((boss.yaw - yaw + math.pi) % (2 * math.pi) - math.pi)
    assert 0 < turned <= math.radians(25) * 0.5 + 1e-9  # slow turn
    states = set()
    hurt = False
    for _ in range(200):
        boss.update(0.05, pc)
        states.add(boss.state)
        hurt = hurt or pc.hp < 5
        pc.invulnerable = 0
    assert STRIKING in states and boss.state in (STANDING, TURNING)


def test_hit_event_hurts_only_in_range_and_not_while_hooked():
    scene, boss = make_boss()
    near = Player(scene, x=0.0, z=-4.0)
    far = Player(scene, x=0.0, z=-30.0)
    for pc, expect in ((near, True), (far, False)):
        boss.state, boss.attack = STRIKING, "sweep"
        boss.play("sweep")
        bones, _ = boss.poses()
        head = rig.transform(bones[boss.rig["bones"].index(next(b for b in boss.rig["bones"] if b["name"] == "head"))], (0, 0, 0))
        pc.x, pc.z = head[0], head[2]
        pc.y = head[1] - 0.9 if expect else pc.y
        boss._events(0, 255, pc)
        assert (pc.hp < 5) == expect
    hooked = Player(scene, x=0.0, z=-4.0)
    hooked.hook = "hooked"
    boss._events(0, 255, hooked)
    assert hooked.hp == 5


def test_both_legs_kneel_then_back_exposes_the_weak_point():
    scene, boss = make_boss(seed=4)
    assert len(boss.legs) == 2 and len(boss.parts) == 3
    first = boss.legs[0]
    assert not boss.damage(first, 1)
    assert boss.hit_slot == first and boss.rig_block().hit_slot == first
    boss.update(0.2, Player(scene))
    assert boss.rig_block().hit_slot == 0xFF  # the flash lasts 0.1 s
    for slot in boss.legs:
        boss.damage(slot, 99)
    assert boss.state == KNEELING and boss.anim == boss.anims["kneel"]
    assert boss.alive & (1 << boss.cover)  # the back is still on
    back = next(s for s in boss.parts if s not in boss.legs)
    boss.damage(back, 99)
    assert not boss.alive & (1 << boss.cover) and boss.alive & (1 << boss.weak)
    assert len(boss.broken) == 4  # two legs, the back and the cover


def test_kneeling_boss_does_not_attack():
    scene, boss = make_boss()
    for slot in boss.legs:
        boss.damage(slot, 99)
    pc = Player(scene, x=0.0, z=-5.0)
    boss.timer = 0
    for _ in range(100):
        boss.update(0.05, pc)
    assert boss.state == KNEELING and pc.hp == 5


def test_weak_point_is_not_shot_and_the_finisher_needs_the_hook():
    scene, boss = make_boss(seed=2)
    pc = Player(scene)
    for slot in boss.parts:
        boss.damage(slot, 99)
    assert boss.weak_exposed()
    assert not boss.damageable(boss.weak, hooked=True)  # shots never break it
    assert not boss.finish_ready(pc)
    pc.hook = "hooked"
    assert boss.finish_ready(pc)
    boss.finish()
    assert boss.defeated() and not boss.alive & (1 << boss.weak)

def test_aim_assist_snaps_to_a_visible_part():
    scene, boss = make_boss(seed=5)
    slot = boss.parts[0]
    centre = next(c for c in boss.colliders() if c.slot == slot).centre()
    eye = vantage(boss, slot)
    # Look 2 degrees to the side of the part's centre.
    yaw = math.atan2(centre[0] - eye[0], centre[2] - eye[2]) + math.radians(2)
    pitch = math.atan2(centre[1] - eye[1], math.hypot(centre[0] - eye[0], centre[2] - eye[2]))
    view = g3d.Camera(*eye, yaw=yaw, pitch=pitch, fov=camera.FOV)
    result = aim.compute(view, boss.colliders())
    assert result.flags & aim.FLAG_PART and result.target.slot == slot
    assert abs(result.dx) > 3  # the reticle moved off centre towards the part
    far = g3d.Camera(*eye, yaw=yaw + math.radians(20), pitch=pitch, fov=camera.FOV)
    assert aim.compute(far, boss.colliders()).flags == 0


def test_shooting_a_part_until_it_breaks():
    scene, boss = make_boss(seed=5)
    slot = boss.parts[0]
    pc = Player(scene, x=0.0, z=-30.0)
    eye = vantage(boss, slot)
    hits = 0
    for _ in range(80):
        c = next((c for c in boss.colliders() if c.slot == slot), None)
        if c is None:
            break
        centre = c.centre()
        dist = math.dist(eye, centre)
        d = tuple((b - a) / dist for a, b in zip(eye, centre))
        shot = aim.Aim(eye, d, flags=aim.FLAG_PART, target=c)
        pc.cooldown = 0
        before = boss.hp[slot]
        pc._shoot(shot, boss.colliders())
        for _ in range(10):
            pc._advance(0.05, boss)
        hits += before - boss.hp[slot]
    assert not boss.alive & (1 << slot) and hits >= 3
    assert boss.broken and boss.broken[0][0] == slot


def test_feet_block_the_pc_but_the_belly_does_not():
    scene, boss = make_boss()
    feet = boss.feet()
    assert len(feet) == 4
    fx, fz, r = feet[0]
    pc = Player(scene, x=fx, z=fz - 3)
    from controls import Input
    for _ in range(40):  # walk straight at the foot
        view = g3d.Camera(pc.x, 2, pc.z - 6, yaw=0.0)
        pc.update(Input(move_y=1.0), camera.ThirdPersonCamera(0.0), 0.05, boss,
                  aim.Aim((0, 0, 0), (0, 0, 1)), [])
        assert math.hypot(pc.x - fx, pc.z - fz) >= r - 1e-6
    pc = Player(scene, x=0.0, z=0.0)  # right under the torso
    pc.update(Input(), camera.ThirdPersonCamera(0.0), 0.05, boss, aim.Aim((0, 0, 0), (0, 0, 1)), [])
    assert (pc.x, pc.z) == (0.0, 0.0)


def test_close_pc_gets_the_stomp_and_the_ring_hurts():
    scene, boss = make_boss()
    pc = Player(scene, x=0.0, z=-5.0)  # under the boss's chest
    boss.timer = 0.0
    attack, hurt_at = None, None
    for i in range(200):
        boss.update(0.05, pc)
        attack = attack or boss.attack
        if pc.hp < 5 and hurt_at is None:
            hurt_at = i
    assert attack == "rear_stomp" and hurt_at is not None
    assert not boss.waves  # spread out to its full radius and gone


def test_the_ring_spares_hooked_and_distant_pcs():
    scene, boss = make_boss()
    near_but_hooked = Player(scene, x=0.0, z=-6.0)
    near_but_hooked.hook = "hooked"
    far = Player(scene, x=0.0, z=-20.0)  # beyond the 14 m ring
    for pc in (near_but_hooked, far):
        boss.waves = [[0.0, 0.0, 0.0, 1, 12.0]]
        for _ in range(40):
            boss._spread(0.05, pc)
        assert pc.hp == 5


def test_ring_objects_scale_and_sink():
    scene, boss = make_boss()
    boss.waves = [[0.0, 0.0, 10.0, 1, 12.0]]
    ring = boss.shockwave_objects()[0]
    ground = world.terrain_height(scene, 0.0, 0.0)
    assert ring.scale == 10.0 and abs(ring.y - (ground - (0.35 * 10 - 1.2))) < 1e-9


def hooked_pc(scene, boss):
    pc = Player(scene, x=3.0, z=0.0)
    pc.y = boss.y + 7.0
    pc.hook = "hooked"
    return pc


def test_shake_then_jump_off_safely():
    scene, boss = make_boss()
    pc = hooked_pc(scene, boss)
    for _ in range(int(2.5 / 0.05) + 2):
        boss.update(0.05, pc)
    assert boss.state == "shaking" and boss.jump_off_warning(pc)
    pc.hook = None  # the player pressed C: let go before the throw
    pc.airborne = True
    for _ in range(40):
        boss.update(0.05, pc)
    assert pc.hp == 5


def test_shake_throws_off_a_pc_that_holds_on():
    scene, boss = make_boss()
    pc = hooked_pc(scene, boss)
    for _ in range(100):
        boss.update(0.05, pc)
        if pc.airborne:
            break
    assert pc.airborne and pc.hook is None and pc.hp == 4
    assert pc.vx * (pc.x - boss.x) + pc.vz * (pc.z - boss.z) > 0  # flung away from the boss


def test_kneels_then_rises_then_kneels_again_after_damage():
    scene, boss = make_boss(seed=4)
    pc = Player(scene, x=0.0, z=-40.0)
    for slot in boss.legs:
        boss.damage(slot, 99)
    assert boss.state == KNEELING
    for _ in range(int((2.5 + 12.0) / 0.05) + 2):
        boss.update(0.05, pc)
    assert boss.state == "rising" and boss.anim == boss.anims["rise"]
    for _ in range(int(2.5 / 0.05) + 2):
        boss.update(0.05, pc)
    assert boss.state == STANDING
    back = next(s for s in boss.parts if s not in boss.legs)
    boss.damage(back, 3)
    assert boss.state == STANDING
    boss.damage(back, 1)
    assert boss.state == KNEELING


def test_kneel_camera_shake_event_fires():
    scene, boss = make_boss()
    for slot in boss.legs:
        boss.damage(slot, 99)
    pc = Player(scene, x=0.0, z=-40.0)
    for _ in range(60):
        boss.update(0.05, pc)
    assert boss.shake > 0
