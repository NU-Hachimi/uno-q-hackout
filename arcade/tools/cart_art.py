#!/usr/bin/env python3
"""Render the cart's art (alia-pad docs/cart.md §1) from the real game with alia-engine, headless.

    python3 tools/cart_art.py OUT_DIR      (alia_engine must be importable: PYTHONPATH)

Writes icon.png (256x256), cover.png and background.png (1280x720) and screenshots/*.png. Build output,
not committed: `make cart` runs it.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import alia_engine as ae  # noqa: E402

import assets  # noqa: E402
import controls  # noqa: E402
import screen  # noqa: E402
import terrain  # noqa: E402
from view import View  # noqa: E402
from game import Game  # noqa: E402

DT = 1 / 30


def raw(jx=0, jy=0, held=0, pressed=0, rx=0, ry=0):
    return controls.RawInput(0, 7, held, pressed, jx, jy, 0, 0, 1000, 0, 0, 0, 0, rx, ry)


def step(engine, game, r):
    """One logic step as alia_engine.run takes it: the world's step hooks around the game's."""
    engine.world.begin_step()
    frame = game.step(r, DT)
    engine.world.end_step(DT)
    return frame


def fight(engine, scene, day, before=None):
    """A fresh round with the ride-in skipped, at `day` seconds into the day cycle (`before`, the last
    round, is taken out of the world)."""
    if before is not None:
        before.close()
    game = Game(scene, engine.world, seed=7)
    for r in (raw(pressed=controls.BTN_A), raw(), raw(pressed=controls.BTN_A)):
        step(engine, game, r)
    game.day = day
    return game


def look_at(game, point, distance, side=0.0):
    """Put the PC `distance` from a point, facing it (offset `side` rad around it), camera on it."""
    p = game.player
    heading = math.atan2(point[0] - p.x, point[2] - p.z) + side
    p.x, p.z = point[0] - math.sin(heading) * distance, point[2] - math.cos(heading) * distance
    p.y = terrain.terrain_height(game.scene, p.x, p.z)
    game.camera.yaw = p.yaw = heading
    game.camera.pitch = math.atan2(point[1] - (p.y + 2.5), distance + 6)


def shoot(engine, view, game, path, hud=True, steps=1, inputs=raw):
    frame = None
    for _ in range(steps):
        frame = step(engine, game, inputs())
    if not hud:
        frame.flags |= screen.FLAG_NO_HUD
    view.set_sky(*terrain.sky_at(game.day))
    view.update(frame)
    view.draw(frame)
    engine.end_frame()
    engine.screenshot(str(path))


def main():
    out = Path(sys.argv[1])
    (out / "screenshots").mkdir(parents=True, exist_ok=True)
    scene = terrain.make_scene(seed=1)

    engine = ae.Engine(headless=True, size=(1280, 720))
    view = View(engine, scene)
    assets.load(engine)
    # Cover: the boss towering over the rider, low and to the side, in the afternoon light.
    game = fight(engine, scene, day=6.0)
    boss = game.boss
    look_at(game, (boss.x, boss.y + 7, boss.z), 24, side=0.5)
    shoot(engine, view, game, out / "cover.png", hud=False)
    # Background (behind the Shell while the cart is selected): dusk, further out.
    game = fight(engine, scene, day=terrain.DAY_HOLD + terrain.DAY_BLEND + 6.0, before=game)
    look_at(game, (boss.x, boss.y + 6, boss.z), 44, side=-0.4)
    shoot(engine, view, game, out / "background.png", hud=False)
    # Screenshots with the HUD: riding in, aiming at a part, at night.
    game = fight(engine, scene, day=6.0, before=game)
    shoot(engine, view, game, out / "screenshots" / "1_ride.png", steps=30, inputs=lambda: raw(jx=-30, jy=100))
    part = next(c for c in game.boss.colliders() if c.slot == game.boss.parts[0]).centre()
    look_at(game, part, 14)
    shoot(engine, view, game, out / "screenshots" / "2_aim.png")
    game = fight(engine, scene, day=2 * (terrain.DAY_HOLD + terrain.DAY_BLEND) + 6.0, before=game)
    look_at(game, (game.boss.x, game.boss.y + 5, game.boss.z), 30, side=0.3)
    shoot(engine, view, game, out / "screenshots" / "3_night.png")
    engine.close()

    # Icon: the boss's head, square, at a chunky 128x128 shown twice as large.
    engine = ae.Engine(headless=True, size=(256, 256), internal=(128, 128))
    view = View(engine, scene)
    assets.load(engine)
    game = fight(engine, scene, day=6.0)
    boss = game.boss
    look_at(game, (boss.x, boss.y + 9, boss.z), 16, side=0.35)
    game.camera.pitch += 0.12
    shoot(engine, view, game, out / "icon.png", hud=False)
    engine.close()
    print(f"wrote cart art to {out}")


if __name__ == "__main__":
    main()
