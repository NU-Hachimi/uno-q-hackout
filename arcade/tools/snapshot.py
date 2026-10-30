#!/usr/bin/env python3
"""Drive the real game with scripted inputs through 44 keyframes and save, for each, the game's state
(NAME.state.json) and, with --alia, alia-engine's picture (NAME.alia.png, headless):

    python3 tools/snapshot.py OUT_DIR --alia
    python3 tools/snapshot_compare.py OLD_DIR OUT_DIR     (the regression check, docs/alia-port.md §5)

alia_engine must be importable (PYTHONPATH): the game plays in its world (headless) either way.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import dataclasses  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402

import alia_engine  # noqa: E402

import assets  # noqa: E402
import controls  # noqa: E402
import world  # noqa: E402
from boss import CHARGING, STRIKING  # noqa: E402
from game import Game  # noqa: E402

DT = 0.05
NEUTRAL_G = (0, 0, 1000)  # mg; unused since the right stick replaced tilt


def raw(jx=0, jy=0, held=0, pressed=0, connected=7, accel=NEUTRAL_G, rx=0, ry=0):
    # Stick values in raw units with preview.py's INVERT_Y: pushing forward reads positive jy.
    return controls.RawInput(0, connected, held, pressed, jx, jy, *accel, 0, 0, 0, 0, rx, ry)


def _rounded(v):
    if isinstance(v, float):
        return round(v, 4) + 0.0  # no -0.0
    if isinstance(v, dict):
        return {k: _rounded(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_rounded(x) for x in v]
    return v


def state_of(game, frame):
    """The game at a keyframe, as plain data (NAME.state.json): what the Frame carries (camera, HUD, objects,
    rigs, hook) and what it doesn't (the PC, the boss, the particles, the sounds). Floats to 4 decimals: two runs of
    the same code are identical."""
    p, b = game.player, game.boss
    return _rounded({
        "game": {"state": game.state, "time": game.time, "sounds": [name for name, _ in game.sounds]},
        "frame": {"camera": dataclasses.asdict(frame.camera), "hud": dataclasses.asdict(frame.hud),
                  "objects": [dataclasses.asdict(o) for o in frame.objects], "hook": dataclasses.asdict(frame.hook),
                  "rigs": [dataclasses.asdict(r) if r else None for r in frame.rigs], "flags": frame.flags},
        "player": {"pos": (p.x, p.y, p.z), "yaw": p.yaw, "hp": p.hp, "hook": p.hook, "airborne": p.airborne,
                   "shots": p.shots, "tracers": len(p.tracers),
                   "particles": {"hits": p.hits.count, "debris": p.debris_fx.count, "orbs": p.orbs.count}},
        "boss": {"pos": (b.x, b.y, b.z), "yaw": b.yaw, "state": b.state, "anim": b.anim, "phase": b.phase(),
                 "hp": {str(k): v for k, v in sorted(b.hp.items())}, "alive": b.alive, "fade": b.fade,
                 "waves": [list(w[:4]) for w in b.waves]},
    })


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    scene = world.make_scene(seed=1)
    engine = alia_engine.Engine(headless=True)
    view = None
    if "--alia" in sys.argv[2:]:
        from alia_view import View
        view = View(engine, scene)  # before the game: it loads the meshes the boss's rig is drawn with
    assets.load(engine)
    game = None

    def new_game():
        """A fresh round (same seed: the same parts), the last one taken out of the world."""
        if game is not None:
            game.close()
        return Game(scene, engine.world, seed=7)

    def step(r, dt):
        """One logic step as alia_engine.run takes it: the world's step hooks around the game's."""
        engine.world.begin_step()
        frame = game.step(r, dt)
        engine.world.end_step(dt)
        return frame

    game = new_game()  # picks this round's parts into scene.slot_variants
    seq = 0

    def save(name, frame):
        (out / f"{name}.state.json").write_text(json.dumps(state_of(game, frame), indent=1, sort_keys=True) + "\n")
        if view:
            view.update(frame, game.player.hand())
            view.draw(frame)
            view.e.end_frame()
            view.e.screenshot(str(out / f"{name}.alia.png"))

    def sky(name, t):
        if view:
            view.set_sky(*world.sky_at(t))

    def run(name, inputs):
        nonlocal seq
        frame = None
        for r in inputs:
            frame = step(r, DT)
        save(name, frame)
        seq += 1

    run("1_ready", [raw()])
    # The intro: A, then the PC gallops in on its own; the boss looms out of the fog
    run("2a_intro_fog", [raw(pressed=controls.BTN_A, held=controls.BTN_A)] + [raw()] * 50)
    run("2b_intro_near", [raw()] * 60)
    intro = 0
    while game.state == "intro" and intro < 400:
        step(raw(), DT)
        intro += 1
    run("2_fight_hint", [raw()])
    # Walk forward and right for 1.5 s, then hold B while turning a little with the right stick.
    walk = [raw(jx=40, jy=110)] * 30
    shoot = [raw(held=controls.BTN_B, rx=70)] * 6
    run("3_walk_shoot", walk + shoot)
    run("4_menu", [raw(pressed=controls.BTN_START, held=controls.BTN_START), raw(jy=-110)])
    run("5_missing", [raw(connected=5)])
    run("6_menu_continue", [raw(pressed=controls.BTN_A, held=controls.BTN_A)])  # Continue (A) back to the fight

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
    run("8_shoot_part", [raw(pressed=controls.BTN_B), raw()])  # one shot: the tracer on its way
    while boss.hp[part] > 1:
        boss.damage(part, 1)
    boss.hit_timer = 0
    run("9_break_part", [raw(pressed=controls.BTN_B)] + [raw()] * 5)
    for slot in boss.parts:
        boss.damage(slot, 99)
    game.boss.broken.clear()
    look_at((boss.x, boss.y + 5, boss.z), 22)
    run("10_kneel", [raw()] * 60)
    hump = next(c for c in boss.colliders() if c.hookable).centre()
    look_at(hump, 12)
    run("11_hook_aim", [raw()])
    run("12_hook_flying", [raw(pressed=controls.BTN_C), raw(), raw()])
    run("13_hooked", [raw()] * 30)
    boss.damage(boss.weak, 99, hooked=True)
    run("14_victory", [raw()])
    # The day cycle at 8 points (holds and blends) on a fresh round.
    game = new_game()
    skip_intro = [raw(pressed=controls.BTN_A, held=controls.BTN_A), raw(), raw(pressed=controls.BTN_A, held=controls.BTN_A)]
    run("15_ride", skip_intro + [raw(jx=-30, jy=100)] * 20 + [raw(held=controls.BTN_B)] * 3)
    period = world.DAY_HOLD + world.DAY_BLEND
    for k in range(8):
        t = (k // 2) * period + (world.DAY_HOLD / 2 if k % 2 == 0 else world.DAY_HOLD + world.DAY_BLEND / 2)
        name = f"16_{k}_day_{t:04.0f}s"
        sky(name, t)
        run(name, [raw()])
    # The stomp's dust ring halfway out, seen from 20 m (outside its reach)
    boss = game.boss
    look_at((boss.x, boss.y + 3, boss.z), 20)
    boss.state, boss.attack = STRIKING, "rear_stomp"
    boss.play("rear_stomp")
    steps = 0
    while not (boss.waves and boss.waves[0][3] >= 7.0) and steps < 100:
        step(raw(), DT)
        steps += 1
    run("17_stomp_ring", [raw()])
    # Mid-charge: the PC 30 m away gets run at, head down
    game = new_game()
    for r in skip_intro:  # Ready -> Intro -> Fight
        step(r, DT)
    boss = game.boss
    game.player.x, game.player.z = boss.x, boss.z - 30
    game.player.yaw = game.camera.yaw = 0.0
    boss.timer = 0.0
    steps = 0
    while not (boss.state == CHARGING and boss.charge_left < 22) and steps < 200:
        step(raw(), DT)
        steps += 1
    run("18_charge", [raw()])

    def run_until(name, done, inputs=None, limit=600):
        """Step with `inputs` (default: nothing pressed) until done() holds, then save that frame."""
        nonlocal seq
        frame = None
        for _ in range(limit):
            frame = step(inputs() if inputs else raw(), DT)
            if done():
                break
        save(name, frame)
        seq += 1

    # Boss attacks on a fresh round (same seed, so the same parts).
    game = new_game()
    run("19_0_start", skip_intro)
    boss, p = game.boss, game.player
    p.x, p.z = 0.0, -6.0  # by the forelegs: close enough for the stomp
    boss.timer = 0.0
    run_until("19_1_stomp_rears", lambda: boss.attack == "rear_stomp" and boss.phase() > 120)
    run_until("19_2_stomp_ring_close", lambda: boss.waves and boss.waves[0][3] > 7.0)
    boss.timer = 99.0  # no ground attacks while the hook frames are taken
    hump = boss.hook_targets()[0].centre()
    p.x, p.z = hump[0] + 12, hump[2]  # from the side
    for _ in range(8):  # the camera orbits with its pitch, so converge on the direction from where it ends up
        v = game.camera.view(p, scene)
        dx, dy, dz = hump[0] - v.x, hump[1] - v.y, hump[2] - v.z
        game.camera.yaw = math.atan2(dx, dz)
        game.camera.pitch = math.atan2(dy, math.hypot(dx, dz))
    p.yaw = game.camera.yaw
    run("20_0_hook", [raw(pressed=controls.BTN_C)])
    run_until("20_1_shake_warning", lambda: boss.jump_off_warning(p) and boss.phase() > 20)
    run_until("20_2_thrown", lambda: p.airborne and p.vy < 2.0)
    for slot in boss.legs:
        boss.damage(slot, 99)
    boss.broken.clear()
    run_until("21_0_kneeling", lambda: boss.anim_time > 3.0)
    run_until("21_1_rising", lambda: boss.state == "rising" and boss.phase() > 120, limit=400)

    # The finisher: every part broken, hooked on the shoulder hump, then B.
    for slot in boss.parts:
        boss.damage(slot, 99)
    boss.broken.clear()
    run_until("22_0_standing_again", lambda: boss.state == "standing", limit=400)
    hump = boss.hook_targets()[0]
    p.hook, p.hook_anchor = "hooked", hump.node
    p.x, p.y, p.z = hump.centre()
    run("22_1_finish_prompt", [raw()])
    run("23_execute_leap", [raw(pressed=controls.BTN_B)] + [raw()] * 8)
    run_until("24_execute_windup", lambda: game.finisher.phase > 110)
    run_until("24_execute_hit", lambda: game.finisher.frozen > 0)
    run_until("25_execute_twist", lambda: game.finisher.phase > 180)
    run_until("25_execute_shatter", lambda: game.finisher.after is not None and game.finisher.after > 0.15)
    run_until("25_execute_drop", lambda: game.finisher.dropped and game.player.vy < -3)
    run_until("26_victory", lambda: game.state == "win")
    print(f"wrote {seq} keyframes to {out}")


if __name__ == "__main__":
    main()
