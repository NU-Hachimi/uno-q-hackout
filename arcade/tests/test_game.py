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
    _, objs, hud, _ = game.step(raw(), DT)
    assert game.state == READY and hud.state == g3d.STATE_READY and hud.msg == 12
    assert len(objs) == 1  # just the PC
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
        _, objs, _, _ = game.step(raw(held=g3d.BTN_B), DT)
    assert len(game.player.bullets) == 2
    assert sum(o.mesh == 1 for o in objs) == 2


def test_tap_shorter_than_a_frame_still_fires():
    game = started()
    game.step(raw(pressed=g3d.BTN_B), DT)
    assert len(game.player.bullets) == 1


def test_menu_navigation_and_restart():
    game = started()
    for _ in range(10):
        game.step(raw(jy=120), DT)
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == MENU
    _, _, hud, _ = game.step(raw(jy=-120), DT)  # stick down -> Restart
    assert hud.state == g3d.STATE_PAUSED and hud.msg == 10
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == READY and game.player.z == -12.0


def test_menu_continue_resumes():
    game = started()
    game.step(raw(pressed=g3d.BTN_A), DT)
    game.step(raw(pressed=g3d.BTN_A), DT)
    assert game.state == FIGHT


def test_missing_controller_pauses_then_resumes_via_menu():
    game = started()
    _, _, hud, _ = game.step(raw(connected=3), DT)  # Movement unplugged
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
