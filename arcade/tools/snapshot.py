#!/usr/bin/env python3
"""Drive the real Python game with scripted inputs and save the scene upload plus a few frames,
so tests/cpp/render_preview.sh --snapshots can render them with the MCU renderer.

    python3 tools/snapshot.py OUT_DIR
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import math  # noqa: E402

import g3d  # noqa: E402
import world  # noqa: E402
from game import Game  # noqa: E402

DT = 0.05
NEUTRAL_G = (0, 0, 1000)  # mg; any pose works, the game calibrates on the A press


def raw(jx=0, jy=0, held=0, pressed=0, connected=7, accel=NEUTRAL_G):
    # Stick values in raw units with preview.py's INVERT_Y: pushing forward reads positive jy.
    return g3d.RawInput(0, connected, held, pressed, jx, jy, *accel, 0, 0, 0, 0)


def write_scene(path, scene):
    header, chunks, crc = g3d.pack_scene(scene)
    out = struct.pack("<H", len(header)) + header + bytes([len(chunks)])
    for kind, index, data in chunks:
        out += struct.pack("<BBH", kind, index, len(data)) + data
    path.write_bytes(out + struct.pack("<H", crc))


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    scene = world.make_scene(seed=1)
    game = Game(scene, seed=7)  # picks this round's parts into scene.slot_variants
    write_scene(out / "scene.bin", scene)
    seq = 0

    def run(name, inputs):
        nonlocal seq
        frame = None
        for r in inputs:
            frame = game.step(r, DT)
        (out / f"{name}.frame").write_bytes(frame.pack(seq))
        seq += 1

    run("1_ready", [raw()])
    run("2_fight_hint", [raw(pressed=g3d.BTN_A, held=g3d.BTN_A), raw()])
    # Walk forward and right for 1.5 s, then hold B while turning a little with tilt.
    walk = [raw(jx=40, jy=110)] * 30
    tilt_right = (300, 0, 950)
    shoot = [raw(held=g3d.BTN_B, accel=tilt_right)] * 6
    run("3_walk_shoot", walk + shoot)
    run("4_menu", [raw(pressed=g3d.BTN_A, held=g3d.BTN_A), raw(jy=-110)])
    run("5_missing", [raw(connected=5)])
    run("6_menu_continue", [raw(pressed=g3d.BTN_A, held=g3d.BTN_A)])  # back to the fight

    def look_at(point, distance):
        """Stand `distance` from a point on the ground, facing it, with the camera on it."""
        p = game.player
        dx, dz = point[0] - p.x, point[2] - p.z
        heading = math.atan2(dx, dz)
        p.x, p.z = point[0] - math.sin(heading) * distance, point[2] - math.cos(heading) * distance
        game.camera.yaw = heading
        game.camera.pitch = math.atan2(point[1] - (p.y + 2.5), distance + 6)

    boss = game.boss
    part = boss.parts[0]
    centre = next(c for c in boss.colliders() if c.slot == part).centre()
    look_at(centre, 14)
    run("7_aim_part", [raw()])
    part = game.aim.target.slot if game.aim.target else part  # the part the reticle snapped to
    run("8_shoot_part", [raw(pressed=g3d.BTN_B), raw()])  # one shot: the tracer on its way
    while boss.hp[part] > 1:
        boss.damage(part, 1)
    boss.hit_timer = 0
    run("9_break_part", [raw(pressed=g3d.BTN_B)] + [raw()] * 5)
    for slot in boss.parts:
        boss.damage(slot, 99)
    game.boss.broken.clear()
    look_at((boss.x, boss.y + 5, boss.z), 22)
    run("10_kneel", [raw()] * 60)
    hump = next(c for c in boss.colliders() if c.hookable).centre()
    look_at(hump, 12)
    run("11_hook_aim", [raw()])
    run("12_hook_flying", [raw(pressed=g3d.BTN_C), raw(), raw()])
    run("13_hooked", [raw()] * 30)
    boss.damage(boss.weak, 99, hooked=True)
    run("14_victory", [raw()])
    # The day cycle at 8 points (holds and blends) on a fresh round; NAME.sky next to NAME.frame is a
    # g3d_scene_sky payload that render_preview.sh applies after the scene.
    game = Game(scene, seed=7)
    run("15_ride", [raw(pressed=g3d.BTN_A, held=g3d.BTN_A)] + [raw(jx=-30, jy=100)] * 20 + [raw(held=g3d.BTN_B)] * 3)
    period = world.DAY_HOLD + world.DAY_BLEND
    for k in range(8):
        t = (k // 2) * period + (world.DAY_HOLD / 2 if k % 2 == 0 else world.DAY_HOLD + world.DAY_BLEND / 2)
        name = f"16_{k}_day_{t:04.0f}s"
        (out / f"{name}.sky").write_bytes(g3d.pack_sky(*world.sky_at(t)))
        run(name, [raw()])

    def run_until(name, done, inputs=None, limit=600):
        """Step with `inputs` (default: nothing pressed) until done() holds, then save that frame."""
        nonlocal seq
        frame = None
        for _ in range(limit):
            frame = game.step(inputs() if inputs else raw(), DT)
            if done():
                break
        (out / f"{name}.frame").write_bytes(frame.pack(seq))
        seq += 1

    # Boss attacks on a fresh round (same seed, so the same parts as scene.bin).
    game = Game(scene, seed=7)
    run("17_0_start", [raw(pressed=g3d.BTN_A, held=g3d.BTN_A)])
    boss, p = game.boss, game.player
    p.x, p.z = 0.0, -6.0  # by the forelegs: close enough for the stomp
    boss.timer = 0.0
    run_until("17_1_stomp_rears", lambda: boss.attack == "rear_stomp" and boss.phase() > 120)
    run_until("17_2_stomp_ring", lambda: boss.waves and boss.waves[0][2] > 7.0)
    boss.timer = 99.0  # no ground attacks while the hook frames are taken
    hump = next(c for c in boss.colliders() if c.hookable).centre()
    p.x, p.z = hump[0] + 12, hump[2]  # from the side: the standing boss's head hides the hump from the front
    for _ in range(8):  # the camera orbits with its pitch, so converge on the direction from where it ends up
        v = game.camera.view(p, scene)
        dx, dy, dz = hump[0] - v.x, hump[1] - v.y, hump[2] - v.z
        game.camera.yaw = math.atan2(dx, dz)
        game.camera.pitch = math.atan2(dy, math.hypot(dx, dz))
    p.yaw = game.camera.yaw
    run("18_0_hook", [raw(pressed=g3d.BTN_C)])
    run_until("18_1_shake_warning", lambda: boss.jump_off_warning(p) and boss.phase() > 20)
    run_until("18_2_thrown", lambda: p.airborne and p.vy < 2.0)
    for slot in boss.legs:
        boss.damage(slot, 99)
    boss.broken.clear()
    run_until("19_0_kneeling", lambda: boss.anim_time > 3.0)
    run_until("19_1_rising", lambda: boss.state == "rising" and boss.phase() > 120, limit=400)

    # The finisher: every part broken, hooked on the shoulder hump, then B.
    import rig as rigmath  # noqa: E402
    from finisher import SHATTER  # noqa: E402
    for slot in boss.parts:
        boss.damage(slot, 99)
    boss.broken.clear()
    run_until("20_0_standing_again", lambda: boss.state == "standing", limit=400)
    hump = next(c for c in boss.colliders() if c.hookable)
    bones, _ = boss.poses()
    top = (hump.centre()[0], hump.centre()[1] + hump.r, hump.centre()[2])
    p.hook, p.hook_bone = "hooked", hump.bone
    p.hook_local = rigmath.transform(rigmath.inverse(bones[hump.bone]), top)
    p.x, p.y, p.z = top
    run("20_1_finish_prompt", [raw()])
    run("21_execute_climb", [raw(pressed=g3d.BTN_B)] + [raw()] * 12)
    run_until("22_execute_strike", lambda: game.finisher.struck >= 2)
    run_until("23_execute_fall", lambda: game.finisher.time > SHATTER + 1.6)
    run_until("24_victory", lambda: game.state == "win")
    print(f"wrote {out}/scene.bin and {seq} frames")


if __name__ == "__main__":
    main()
