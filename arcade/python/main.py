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
releases the hook, A opens the menu and confirms, L3 is the stick press.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "python"))

import alia_engine as ae  # noqa: E402

import audio  # noqa: E402
import g3d  # noqa: E402
import world  # noqa: E402
from alia_view import View  # noqa: E402
from game import Game  # noqa: E402

# Alia Pad buttons are positional; the labels are Nintendo-style (A = East, B = South, X = North).
BUTTONS = ((ae.EAST, g3d.BTN_A), (ae.SOUTH, g3d.BTN_B), (ae.NORTH, g3d.BTN_C), (ae.R1, g3d.BTN_C),
           (ae.L3, g3d.BTN_STICK))


def _bits(state):
    return sum({b for pad, b in BUTTONS if state & pad})


def raw_input(inp, seq):
    """alia_engine.Input -> the g3d.RawInput the game reads (sticks in raw -127..127 units, y up)."""
    axis = lambda v: max(-127, min(127, round(v * 127)))  # noqa: E731
    return g3d.RawInput(seq_ack=seq, connected=7, held=_bits(inp.held), pressed=_bits(inp.pressed),
                        jx=axis(inp.lx), jy=axis(-inp.ly), ax=0, ay=0, az=1000, gx=0, gy=0, render_ms=0, push_ms=0,
                        rx=axis(inp.rx), ry=axis(-inp.ry))


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
        self.scene = world.make_scene(seed=1, look=world.TIME_OF_DAY[0])
        self.game = Game(self.scene)
        self.view = View(engine, self.scene)
        self.music = audio.Music()
        self.seq = 0
        self.frame = self.game.step(None, 0.0)  # something to draw before the first step
        print(f"Megalith on {engine.describe()}", flush=True)

    def fixed_update(self, engine, dt):
        raw = self.demo(self.seq) if self.demo else raw_input(engine.input, self.seq)
        self.frame = self.game.step(raw, dt)
        if self.game.sky_update(dt):
            self.view.set_sky(*world.sky_at(self.game.day))
        self.music.play(*self.game.music())
        self.seq = (self.seq + 1) & 0xFF

    def render(self, engine, alpha):
        self.view.draw(self.frame)

    def shutdown(self, engine):
        self.music.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="scripted input instead of the controller")
    args = parser.parse_args(ae.strip_runtime_flags(sys.argv[1:]))
    ae.run(Megalith(demo=args.demo), argv=sys.argv[1:], title="Megalith")


if __name__ == "__main__":
    main()
