import math

import g3d
import world
from controls import Controls
from game import FIGHT, FIGHT_SPAWN, INTRO, MENU, MISSING, READY, READY_SPAWN, Game

DT = 0.05


def raw(jx=0, jy=0, held=0, pressed=0, connected=7, accel=(0, 0, 1000)):
    return g3d.RawInput(0, connected, held, pressed, jx, jy, *accel, 0, 0, 0, 0)


def started():
    """A fight with the intro skipped (A starts it, A again skips it)."""
    game = Game(world.make_scene(1))
    game.step(raw(pressed=g3d.BTN_A), DT)
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == FIGHT
    return game


def test_ready_shows_prompt_and_a_starts():
    game = Game(world.make_scene(1))
    frame = game.step(raw(), DT)
    assert game.state == READY and frame.hud.state == g3d.STATE_READY and frame.hud.msg == 12
    assert frame.objects == []  # the PC is drawn as rigs: horse and rider
    boss, horse, rider = frame.rigs
    assert (boss.rig_id, horse.rig_id, rider.rig_id) == (1, 3, 4) and horse.char_light and rider.char_light
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == INTRO


def test_ready_rides_back_and_forth_beyond_the_fog_with_the_boss_hidden():
    game = Game(world.make_scene(1))
    xs = []
    for _ in range(2400):  # 2 minutes: long enough to turn back at both ends
        frame = game.step(raw(), DT)
        p = game.player
        xs.append(p.x)
        assert abs(p.z - READY_SPAWN[1]) < 12.0
        assert math.hypot(p.x - game.boss.x, p.z - game.boss.z) > 95.0
        assert frame.rigs[0].fade == 1.0
        behind = (game.camera.yaw - p.yaw + math.pi) % (2 * math.pi) - math.pi
        assert abs(behind) < 1.0  # the riding camera, no orbit
    assert not game.player.standing  # galloping, not standing still
    assert max(xs) > 30.0 and min(xs) < -30.0


def test_intro_rides_up_to_the_boss_then_hands_over():
    game = Game(world.make_scene(1))
    for _ in range(40):
        game.step(raw(), DT)
    game.step(raw(pressed=g3d.BTN_A), DT)
    fades, dist = [], []
    for _ in range(400):
        frame = game.step(raw(jx=127, jy=-127), DT)  # the stick does nothing during the intro
        if game.state != INTRO:
            break
        assert frame.flags & g3d.FLAG_NO_HUD and game.player.hp == 5
        fades.append(frame.rigs[0].fade)
        dist.append(math.hypot(game.player.x - game.boss.x, game.player.z - game.boss.z))
    assert game.state == FIGHT
    assert 6.0 < len(fades) * DT < 16.0  # seconds
    assert fades == sorted(fades, reverse=True) and fades[-1] == 0.0
    assert dist[0] > 95.0 and dist == sorted(dist, reverse=True)  # steadily closer
    p = game.player
    assert (p.x, p.z) == FIGHT_SPAWN and abs(p.yaw) < 1e-9 and game.boss.state == "standing"


def test_a_skips_the_intro():
    game = Game(world.make_scene(1))
    game.step(raw(pressed=g3d.BTN_A), DT)
    game.step(raw(), DT)
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == FIGHT and (game.player.x, game.player.z) == FIGHT_SPAWN
    assert game.step(raw(), DT).rigs[0].fade == 0.0


def test_stick_forward_walks_away_from_camera():
    game = started()
    x0, z0 = game.player.x, game.player.z
    for _ in range(20):
        game.step(raw(jy=120), DT)
    fx, fz = math.sin(game.camera.yaw), math.cos(game.camera.yaw)
    moved = (game.player.x - x0) * fx + (game.player.z - z0) * fz
    assert 4.0 < moved <= 6.0 * 20 * DT + 1e-6


def test_holding_b_fires_at_cooldown_rate():
    game = started()
    for _ in range(6):  # 0.3 s with a 0.25 s cooldown -> two shots
        frame = game.step(raw(held=g3d.BTN_B), DT)
    assert game.player.shots == 2
    assert sum(o.mesh == 1 for o in frame.objects) == 2  # both tracers still flying


def test_tap_shorter_than_a_frame_still_fires():
    game = started()
    game.step(raw(pressed=g3d.BTN_B), DT)
    assert game.player.shots == 1


def test_menu_navigation_and_restart():
    game = started()
    for _ in range(10):
        game.step(raw(jy=120), DT)
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == MENU
    hud = game.step(raw(jy=-120), DT).hud  # stick down -> Restart
    assert hud.state == g3d.STATE_PAUSED and hud.msg == 10
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == READY and (game.player.x, game.player.z) == READY_SPAWN


def test_menu_continue_resumes():
    game = started()
    game.step(raw(pressed=g3d.BTN_A), DT)
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == FIGHT


def test_missing_controller_pauses_then_resumes_via_menu():
    game = started()
    hud = game.step(raw(connected=3), DT).hud  # Movement unplugged
    assert game.state == MISSING and hud.msg == 8
    game.step(raw(), DT)
    assert game.state == MENU


def test_failed_frame_is_neutral_input():
    game = started()
    x0 = game.player.x
    game.step(None, DT)
    assert game.player.x == x0


def test_tilt_is_rate_control_with_dead_zone():
    controls = Controls()
    controls.update(raw())
    controls.calibrate()
    tilt = lambda s: tuple(int(1000 * (a * s + n)) for a, n in zip(controls.yaw_axis, (0, 0, 1)))
    for _ in range(20):  # let the low-pass filter settle
        small = controls.update(raw(accel=tilt(0.05)))
    assert small.yaw_rate == 0.0
    for _ in range(20):
        big = controls.update(raw(accel=tilt(0.4)))
    assert big.yaw_rate > 0.5
    for _ in range(20):
        back = controls.update(raw())
    assert back.yaw_rate == 0.0


def test_axis_vector_parsing():
    import pytest
    from controls import axis_vector
    assert axis_vector("x") == (1.0, 0.0, 0.0)
    assert axis_vector("-y") == (0.0, -1.0, 0.0)
    assert axis_vector("z", invert=True) == (0.0, 0.0, -1.0)
    with pytest.raises(ValueError):
        axis_vector("w")


def test_shooting_does_not_turn_the_horse():
    game = started()
    yaw = game.player.yaw
    game.camera.yaw += 1.0  # look well off to the side, then shoot
    for _ in range(3):
        game.step(raw(held=g3d.BTN_B), DT)
    assert game.player.tracers and game.player.yaw == yaw


def test_idle_horse_stands_and_moving_gallops():
    game = started()
    game.step(raw(), DT)
    horse = game.rigs()[1]
    assert game.player.standing and horse.anim == 2  # stand
    game.step(raw(jy=120), DT)
    assert not game.player.standing and game.rigs()[1].anim == 0  # gallop


def test_stick_steers_horse_and_camera_together():
    game = started()
    offset = game.camera.yaw - game.player.yaw
    for _ in range(10):
        game.step(raw(jx=120), DT)  # full right, no throttle: turn on the spot
    assert game.player.yaw < -0.5  # turning right lowers yaw
    assert abs((game.camera.yaw - game.player.yaw) - offset) < 1e-9


def test_each_round_fits_two_legs_the_back_and_the_head():
    import random
    from boss import pick_parts, slots_tagged
    from gen.rigs import RIGS
    moose = RIGS[1]
    parts = slots_tagged(moose, "phase1", "phase2")
    head = slots_tagged(moose, "cover", "weak")
    combos = set()
    for seed in range(20):
        variants = pick_parts(random.Random(seed))
        fitted = [s for s in parts if variants[s]]
        assert len(fitted) == 3 and all(variants[s] == 1 for s in head)
        assert sum(variants[s] > 0 for s in slots_tagged(moose, "leg")) == 2
        assert all(variants[s] for s in slots_tagged(moose, "back"))
        assert not any(variants[s] for s in slots_tagged(moose, "neck"))
        assert all(1 <= variants[s] < len(moose["slots"][s]["variants"]) for s in fitted)
        combos.add(tuple(variants))
    assert len(combos) > 5


def test_restart_picks_new_parts_and_bumps_scene_version():
    game = Game(world.make_scene(1), seed=3)
    first, version = list(game.scene.slot_variants), game.scene_version
    seen = {tuple(first)}
    for _ in range(5):
        game.restart()
        seen.add(tuple(game.scene.slot_variants))
    assert game.scene_version == version + 5 and len(seen) > 1


def test_frame_carries_the_boss_rig():
    game = started()
    frame = game.step(raw(), DT)
    assert frame.rigs[0].rig_id == 1 and frame.rigs[0].part_alive == game.boss.alive
    assert bin(frame.rigs[0].part_alive).count("1") == 5  # two legs, the back, cover and weak point
    assert frame.hud.boss_hp == 255


def test_tap_during_cooldown_fires_when_it_ends():
    game = started()
    game.step(raw(pressed=g3d.BTN_B), DT)
    game.step(raw(pressed=g3d.BTN_B), DT)  # 0.05 s later, still cooling down
    assert game.player.shots == 1
    for _ in range(5):
        game.step(raw(), DT)
    assert game.player.shots == 2


def test_music_follows_the_round():
    game = Game(world.make_scene(1))
    assert game.music() == ("bgm_battle", 0.5)  # Ready: the theme, softer
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.music() == ("bgm_battle", 1.0)  # the intro: full volume
    game.step(raw(pressed=g3d.BTN_A), DT)  # skip it
    game.player.hp = 0
    game.step(raw(), DT)
    assert game.state == "lose" and game.music() == ("jingle_defeat", 1.0)
