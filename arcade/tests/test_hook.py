import math
import random

import aim
import camera
import g3d
import rig
import world
from boss import Boss, pick_parts
from controls import Input
from gen import palette
from game import LOSE, READY, WIN, Game
from player import HOOKED, PULLING, Player

DT = 0.05


def setup(seed=3):
    scene = world.make_scene(1)
    scene.slot_variants = pick_parts(random.Random(seed))
    boss = Boss(scene, random.Random(0))
    return scene, boss


def look_at(pc, centre):
    """A camera behind the PC looking straight at `centre`."""
    view = g3d.Camera(pc.x, pc.y + 2.5, pc.z, fov=camera.FOV)
    d = tuple(b - a for a, b in zip((view.x, view.y, view.z), centre))
    view.yaw = math.atan2(d[0], d[2])
    view.pitch = math.atan2(d[1], math.hypot(d[0], d[2]))
    return view


def hook_view(boss, pc):
    """A camera behind the PC looking straight at the boss's brow, the only hook point."""
    brow = boss.hook_targets()[1]
    return look_at(pc, brow.centre()), brow


def step(pc, boss, inp=Input(), view=None):
    colliders = boss.colliders()
    a = aim.compute(view, colliders, pc.hand(), boss.hook_targets()) if view else aim.Aim((0, 0, 0), (0, 0, 1))
    pc.update(inp, camera.ThirdPersonCamera(0.0), DT, boss, a, colliders)
    return a


def test_hook_flies_pulls_and_rides_the_bone():
    scene, boss = setup()
    pc = Player(scene, x=0.0, z=-14.0)
    view, brow = hook_view(boss, pc)
    a = step(pc, boss, view=view)
    assert a.flags & aim.FLAG_HOOK and a.hook.collider.kind == "hook"
    step(pc, boss, Input(pressed=g3d.BTN_C), view)
    assert pc.hook == "flying" and pc.hook_block().flags == 1
    for _ in range(80):
        step(pc, boss)
        if pc.hook == HOOKED:
            break
    assert pc.hook == HOOKED and pc.hook_block().flags == 3
    anchor = pc.anchor(boss)
    assert math.dist((pc.x, pc.y, pc.z), anchor) < 1e-9 and pc.y > 6.0  # up on the boss
    assert math.dist(anchor, boss.hook_targets()[1].centre()) < 1e-6  # on the brow, wherever the head moved
    boss.yaw += 0.5  # the boss turns: the PC moves with the bone
    boss._cache = None
    step(pc, boss)
    assert math.dist((pc.x, pc.y, pc.z), pc.anchor(boss)) < 1e-9
    assert math.dist(anchor, pc.anchor(boss)) > 1.0


def test_only_the_back_and_the_brow_take_the_hook():
    scene, boss = setup()
    hump, brow = boss.hook_targets()
    pc = Player(scene, x=14.0, z=0.0)  # beside the boss: both in view
    for target in (hump, brow):
        a = step(pc, boss, view=look_at(pc, target.centre()))
        assert a.flags & aim.FLAG_HOOK and a.hook.collider == target
    legs = next(c for c in boss.colliders() if c.kind == "body" and c.bone == 3)  # a foreleg
    a = step(pc, boss, view=look_at(pc, legs.centre()))
    assert not a.flags & aim.FLAG_HOOK
    behind = Player(scene, x=0.0, z=14.0)  # behind it: the body hides the brow
    a = step(behind, boss, view=look_at(behind, brow.centre()))
    assert not (a.hook and a.hook.collider == brow)


def test_on_the_brow_the_view_tilts_further_down_and_eases_back_after():
    from tilt_config import HOOKED_MIN_PITCH_DEG, MIN_PITCH_DEG
    cam = camera.ThirdPersonCamera(0.0)
    down = Input(pitch_rate=-math.radians(40))
    for _ in range(60):
        cam.turn(down, DT, on_boss=True)
    assert abs(math.degrees(cam.pitch) - HOOKED_MIN_PITCH_DEG) < 1e-9
    cam.turn(Input(), DT)  # let go: no jump back to the riding limit
    assert math.degrees(cam.pitch) < MIN_PITCH_DEG - 10
    for _ in range(40):
        cam.turn(down, DT)
    assert abs(math.degrees(cam.pitch) - MIN_PITCH_DEG) < 1e-9


def test_letting_go_falls_to_the_ground():
    scene, boss = setup()
    pc = Player(scene, x=0.0, z=-14.0)
    view, _ = hook_view(boss, pc)
    step(pc, boss, Input(pressed=g3d.BTN_C), view)
    for _ in range(80):
        step(pc, boss)
    assert pc.hooked
    step(pc, boss, Input(pressed=g3d.BTN_C))
    assert pc.hook is None and pc.airborne
    for _ in range(60):
        step(pc, boss)
    assert not pc.airborne and abs(pc.y - world.terrain_height(scene, pc.x, pc.z)) < 1e-9


def test_a_miss_comes_back():
    scene, boss = setup()
    pc = Player(scene, x=0.0, z=-14.0)
    view = g3d.Camera(pc.x, pc.y + 2.5, pc.z, yaw=math.pi, fov=camera.FOV)  # facing away from the boss
    a = step(pc, boss, Input(pressed=g3d.BTN_C), view)
    assert not a.flags & aim.FLAG_HOOK and pc.hook == "flying"
    for _ in range(20):
        step(pc, boss)
    assert pc.hook is None and not pc.airborne


def test_hooked_shots_do_double_damage():
    scene, boss = setup()
    back = next(s for s in boss.parts if s not in boss.legs)
    pc = Player(scene)
    pc.hook = HOOKED
    part = next(c for c in boss.colliders() if c.slot == back)
    eye = part.centre()[0], part.centre()[1] + 4, part.centre()[2] + 1
    d = tuple((b - a) / math.dist(eye, part.centre()) for a, b in zip(eye, part.centre()))
    before = boss.hp[back]
    pc._shoot(aim.Aim(eye, d), boss.colliders())
    for _ in range(10):
        pc._advance(DT, boss)
    assert boss.hp[back] == before - 2

def test_cannot_be_hurt_while_riding_the_hook():
    scene, boss = setup()
    pc = Player(scene)
    pc.hook = PULLING
    assert not pc.hurt(1) and pc.hp == 5
    pc.hook = None
    assert pc.hurt(1) and pc.hp == 4 and not pc.hurt(1)  # then invulnerable for a second


def raw(pressed=0):
    return g3d.RawInput(0, 7, 0, pressed, 0, 0, 0, 0, 1000, 0, 0, 0, 0)


def hook_on_brow(pc, boss):
    brow = boss.hook_targets()[1]
    bones, _ = boss.poses()
    pc.hook, pc.hook_bone = HOOKED, brow.bone
    pc.hook_local = rig.transform(rig.inverse(bones[brow.bone]), brow.centre())
    pc.x, pc.y, pc.z = brow.centre()


def test_finisher_prompts_then_b_plays_it_and_wins():
    from finisher import EXECUTE_SECONDS, HIT_STOP, SLOW
    from game import EXECUTE, MSG_FINISH
    game = Game(world.make_scene(1), seed=1)
    game.step(raw(g3d.BTN_A), DT)
    game.step(raw(g3d.BTN_A), DT)  # skip the intro
    boss, pc = game.boss, game.player
    for slot in boss.parts:
        boss.damage(slot, 99)
    hook_on_brow(pc, boss)
    boss.timer = 99.0
    frame = game.step(raw(), DT)
    assert frame.hud.msg == MSG_FINISH
    shots = pc.shots
    frame = game.step(raw(g3d.BTN_B), DT)
    assert game.state == EXECUTE and pc.shots == shots  # B finished instead of shooting
    fin = game.finisher
    time, hit, shattered = 0.0, None, None
    while game.state == EXECUTE and time < 20.0:
        frame = game.step(raw(), DT)
        time += DT
        if game.state == EXECUTE:
            assert frame.flags & g3d.FLAG_NO_HUD and frame.hook.flags == 0 and len(frame.objects) <= g3d.MAX_OBJ
        if hit is None and fin.frozen > 0:
            hit = time
            assert math.dist(fin._hand(), fin.weak_point()) < 0.3  # the hook goes into the weak point
            assert frame.objects[0].tint == palette.FLASH and len(fin.orbs) == 8
        if shattered is None and boss.defeated():
            shattered = time
    expect_hit = fin.hit_phase / 255 * EXECUTE_SECONDS
    expect_shatter = expect_hit + HIT_STOP + (fin.shatter_phase - fin.hit_phase) / 255 * EXECUTE_SECONDS / SLOW
    assert abs(hit - expect_hit) < 2 * DT and abs(shattered - expect_shatter) < 2 * DT
    assert game.state == WIN and frame.hud.msg == 13
    assert boss.fade == 1.0  # sank into the fog
    assert pc.hook is None and not pc.airborne and pc.y == world.terrain_height(game.scene, pc.x, pc.z)  # back in the saddle
    game.step(raw(g3d.BTN_A), DT)
    assert game.state == READY

def test_losing_all_health_loses():
    game = Game(world.make_scene(1), seed=1)
    game.step(raw(g3d.BTN_A), DT)
    game.step(raw(g3d.BTN_A), DT)  # skip the intro
    game.player.hp = 0
    frame = game.step(raw(), DT)
    assert game.state == LOSE and frame.hud.msg == 14
