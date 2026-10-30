"""Megalith on Alia Pad: game logic in Python, drawn by alia-engine (alia_view.py).

    python3 main.py            window: keyboard or gamepad (alia_engine.Input)
    python3 main.py --demo     scripted input instead of the controller

alia-engine owns the loop and the display (its architecture §2.1): the internal resolution comes
from cart.toml, the window from the compositor, and the common flags (--headless, --frames N,
--screenshot PATH, --stats, --input-log, ...) work for every cart, e.g.
    python3 main.py --headless --frames 300 --screenshot out.png --demo

The engine module comes from ./python next to this file (a cart's content/python, from
`make cart`) or from PYTHONPATH during development (an alia-engine build directory).
Controls (Alia Pad labels): left stick rides, right stick looks, B shoots, X or R1 fires and
releases the hook, Start opens and closes the pause menu, A confirms in it (and A or Start starts a round),
L3 is the stick press.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "python"))

import alia_engine as ae  # noqa: E402

import assets  # noqa: E402
import audio  # noqa: E402
import g3d  # noqa: E402
import world  # noqa: E402
from alia_view import View  # noqa: E402
from game import Game  # noqa: E402

# The controls as alia-engine input actions (its docs/api.md §6). Alia Pad buttons are positional; the labels
# are Nintendo-style (A = East, B = South, X = North). Each action is one of the g3d button bits the game reads.
ACTIONS = {"confirm": ["EAST"], "shoot": ["SOUTH"], "hook": ["NORTH", "R1"], "stick": ["L3"], "pause": ["START"],
           "ride": {"stick": "left"}, "look": {"stick": "right"}}  # controls.py applies the dead zones
ACTION_BITS = (("confirm", g3d.BTN_A), ("shoot", g3d.BTN_B), ("hook", g3d.BTN_C), ("stick", g3d.BTN_STICK),
               ("pause", g3d.BTN_START))


def raw_input(actions, seq):
    """alia_engine.Actions -> the g3d.RawInput the game reads (sticks in raw -127..127 units, y up)."""
    axis = lambda v: max(-127, min(127, round(v * 127)))  # noqa: E731
    held = sum(bit for name, bit in ACTION_BITS if actions.held(name))
    pressed = sum(bit for name, bit in ACTION_BITS if actions.pressed(name))
    (jx, jy), (rx, ry) = actions.axis("ride"), actions.axis("look")
    return g3d.RawInput(seq_ack=seq, connected=7, held=held, pressed=pressed, jx=axis(jx), jy=axis(-jy), ax=0, ay=0,
                        az=1000, gx=0, gy=0, render_ms=0, push_ms=0, rx=axis(rx), ry=axis(-ry))


class DemoInput:
    """Scripted input: A to start the ride-in, A to skip it, then ride and look."""

    def __init__(self):
        self.step = 0

    def __call__(self, seq):
        self.step += 1
        pressed = g3d.BTN_A if self.step in (5, 10) else 0
        jy, rx = (60, 40) if self.step > 20 else (0, 0)
        return g3d.RawInput(seq, 7, 0, pressed, 0, jy, 0, 0, 1000, 0, 0, 0, 0, rx, 0)


class Megalith:
    """alia_engine.run() calls these: logic at a fixed 60 Hz, drawing once per displayed frame."""

    def __init__(self, demo=False):
        self.demo = DemoInput() if demo else None

    def init(self, engine):
        engine.actions.load(ACTIONS)
        self.scene = world.make_scene(seed=1, look=world.TIME_OF_DAY[0])
        self.view = View(engine, self.scene)  # first: it loads the meshes the rigs are drawn with
        assets.load(engine)
        self.game = Game(self.scene, engine.world)
        self.music = audio.Music()
        self.seq = 0
        self.frame = self.game.step(None, 0.0)  # something to draw before the first step
        self.view.update(self.frame, self.game.player.hand())
        print(f"Megalith on {engine.describe()}", flush=True)

    def fixed_update(self, engine, dt):
        raw = self.demo(self.seq) if self.demo else raw_input(engine.actions, self.seq)
        self.frame = self.game.step(raw, dt)
        self.view.update(self.frame, self.game.player.hand())  # the world follows the logic; the engine interpolates between steps
        if self.game.sky_update(dt):
            self.view.set_sky(*world.sky_at(self.game.day))
        self.music.play(*self.game.music())
        self.seq = (self.seq + 1) & 0xFF

    def render(self, engine, alpha):
        self.view.draw(self.frame)  # the HUD

    def shutdown(self, engine):
        self.music.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="scripted input instead of the controller")
    args = parser.parse_args(ae.strip_runtime_flags(sys.argv[1:]))
    ae.run(Megalith(demo=args.demo), argv=sys.argv[1:], title="Megalith")


if __name__ == "__main__":
    main()
