import math

import g3d
import world
from controls import Controls
from game import FIGHT, MENU, MISSING, READY, Game

DT = 0.05


def raw(jx=0, jy=0, held=0, pressed=0, connected=7, accel=(0, 0, 1000)):
    return g3d.RawInput(0, connected, held, pressed, jx, jy, *accel, 0, 0, 0, 0)


def started():
    game = Game(world.make_scene(1))
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == FIGHT
    return game


def test_ready_shows_prompt_and_a_starts():
    game = Game(world.make_scene(1))
    frame = game.step(raw(), DT)
    assert game.state == READY and frame.hud.state == g3d.STATE_READY and frame.hud.msg == 12
    assert len(frame.objects) == 1  # just the PC
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == FIGHT


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
    assert game.state == READY and game.player.z == -30.0


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
    assert frame.rig.rig_id == 1 and frame.rig.part_alive == game.boss.alive
    assert bin(frame.rig.part_alive).count("1") == 5  # two legs, the back, cover and weak point
    assert frame.hud.boss_hp == 255


def test_tap_during_cooldown_fires_when_it_ends():
    game = started()
    game.step(raw(pressed=g3d.BTN_B), DT)
    game.step(raw(pressed=g3d.BTN_B), DT)  # 0.05 s later, still cooling down
    assert game.player.shots == 1
    for _ in range(5):
        game.step(raw(), DT)
    assert game.player.shots == 2
