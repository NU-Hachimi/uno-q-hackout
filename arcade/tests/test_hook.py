import math
import random

import aim
import camera
import g3d
import world
from boss import Boss, pick_parts
from controls import Input
from game import LOSE, READY, WIN, Game
from player import HOOKED, PULLING, Player

DT = 0.05


def setup(seed=3):
    scene = world.make_scene(1)
    scene.slot_variants = pick_parts(random.Random(seed))
    boss = Boss(scene, random.Random(0))
    return scene, boss


def hook_view(boss, pc):
    """A camera behind the PC looking straight at the boss's shoulder-hump hook point."""
    hump = next(c for c in boss.colliders() if c.hookable)
    centre = hump.centre()
    view = g3d.Camera(pc.x, pc.y + 2.5, pc.z, fov=camera.FOV)
    d = tuple(b - a for a, b in zip((view.x, view.y, view.z), centre))
    view.yaw = math.atan2(d[0], d[2])
    view.pitch = math.atan2(d[1], math.hypot(d[0], d[2]))
    return view, hump


def step(pc, boss, inp=Input(), view=None):
    colliders = boss.colliders()
    a = aim.compute(view, colliders, pc.hand()) if view else aim.Aim((0, 0, 0), (0, 0, 1))
    pc.update(inp, camera.ThirdPersonCamera(0.0), DT, boss, a, colliders)
    return a


def test_hook_flies_pulls_and_rides_the_bone():
    scene, boss = setup()
    pc = Player(scene, x=0.0, z=-14.0)
    view, hump = hook_view(boss, pc)
    a = step(pc, boss, view=view)
    assert a.flags & aim.FLAG_HOOK and a.hook.collider.hookable
    step(pc, boss, Input(pressed=g3d.BTN_C), view)
    assert pc.hook == "flying" and pc.hook_block().flags == 1
    for _ in range(80):
        step(pc, boss)
        if pc.hook == HOOKED:
            break
    assert pc.hook == HOOKED and pc.hook_block().flags == 3
    anchor = pc.anchor(boss)
    assert math.dist((pc.x, pc.y, pc.z), anchor) < 1e-9 and pc.y > 6.0  # up on the boss
    boss.yaw += 0.5  # the boss turns: the PC moves with the bone
    boss._cache = None
    step(pc, boss)
    assert math.dist((pc.x, pc.y, pc.z), pc.anchor(boss)) < 1e-9
    assert math.dist(anchor, pc.anchor(boss)) > 1.0


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


def test_finisher_prompts_then_b_plays_it_and_wins():
    from finisher import DIE, SHATTER, TAIL
    from game import EXECUTE, MSG_FINISH
    game = Game(world.make_scene(1), seed=1)
    game.step(raw(g3d.BTN_A), DT)
    boss, pc = game.boss, game.player
    for slot in boss.parts:
        boss.damage(slot, 99)
    pc.hook = HOOKED
    pc.x, pc.y, pc.z = boss.x, boss.y + 8.0, boss.z - 2.0
    boss.timer = 99.0
    frame = game.step(raw(), DT)
    assert frame.hud.msg == MSG_FINISH
    shots = pc.shots
    frame = game.step(raw(g3d.BTN_B), DT)
    assert game.state == EXECUTE and pc.shots == shots  # B finished instead of shooting
    frame = game.step(raw(), DT)
    assert frame.flags & g3d.FLAG_NO_HUD
    for _ in range(int((SHATTER + DIE + TAIL) / DT) + 2):
        frame = game.step(raw(), DT)
    assert game.state == WIN and frame.hud.msg == 13 and boss.defeated()
    assert boss.fade == 1.0  # sank into the fog
    game.step(raw(g3d.BTN_A), DT)
    assert game.state == READY

def test_losing_all_health_loses():
    game = Game(world.make_scene(1), seed=1)
    game.step(raw(g3d.BTN_A), DT)
    game.player.hp = 0
    frame = game.step(raw(), DT)
    assert game.state == LOSE and frame.hud.msg == 14
