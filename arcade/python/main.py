"""Megalith on Alia Pad: game logic in Python, drawn by alia-engine (alia_view.py).

    python3 main.py                                 window: keyboard or gamepad (alia_engine.Input)
    python3 main.py --headless --frames 300 --shot out.png --demo    offscreen, e.g. screenshots

The engine module comes from ./python next to this file (a cart's content/python, from
`make cart`) or from PYTHONPATH during development (alia-engine's build directory).
Controls (Alia Pad labels): left stick rides, right stick looks, B shoots, X or R1 fires and
releases the hook, A opens the menu and confirms, L3 is the stick press.
"""

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "python"))

import alia_engine as ae  # noqa: E402

import audio  # noqa: E402
import g3d  # noqa: E402
import world  # noqa: E402
from alia_view import View  # noqa: E402
from game import Game  # noqa: E402

MAX_DT = 0.1  # s; clamp long stalls so the game does not jump
CART_ID = "com.nuhachimi.megalith"

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
    """Scripted input for headless runs: A to start the ride-in, A to skip it, then ride and look."""

    def __init__(self):
        self.frame = 0

    def __call__(self, seq):
        self.frame += 1
        pressed = g3d.BTN_A if self.frame in (5, 10) else 0
        jy, rx = (60, 40) if self.frame > 20 else (0, 0)
        return g3d.RawInput(seq, 7, 0, pressed, 0, jy, 0, 0, 1000, 0, 0, 0, 0, rx, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--headless", action="store_true", help="offscreen (surfaceless EGL), no window")
    parser.add_argument("--frames", type=int, default=0, help="stop after this many frames (0: run until quit)")
    parser.add_argument("--shot", help="write the last frame to this PNG")
    parser.add_argument("--demo", action="store_true", help="scripted input instead of the controller")
    parser.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270), help="output rotation")
    parser.add_argument("--stats", action="store_true", help="print frame timing every few seconds")
    parser.add_argument("--input-log", action="store_true", help="log the gamepad mapping and button presses")
    args = parser.parse_args()
    if args.input_log:
        os.environ["ALIA_INPUT_LOG"] = "1"  # read by the engine when it opens the window

    engine = ae.Engine(title="Megalith", app_id=os.environ.get("ALIA_CART_ID", CART_ID),
                       headless=args.headless, rotate=args.rotate)
    scene = world.make_scene(seed=1, look=world.TIME_OF_DAY[0])
    game = Game(scene)
    view = View(engine, scene)
    music = audio.Music()
    demo = DemoInput() if args.demo else None
    running = [True]
    signal.signal(signal.SIGTERM, lambda *_: running.__setitem__(0, False))  # alia-session's stop
    print(f"Megalith on {engine.describe()}", flush=True)

    seq, n, last, report = 0, 0, time.monotonic(), time.monotonic()
    step_ms = 0.0
    while running[0] and engine.poll():
        now = time.monotonic()
        dt = 1 / 60 if args.headless else min(now - last, MAX_DT)
        last = now
        raw = demo(seq) if demo else raw_input(engine.input, seq)
        t0 = time.perf_counter()
        frame = game.step(raw, dt)
        if game.sky_update(dt):
            view.set_sky(*world.sky_at(game.day))
        music.play(*game.music())
        view.draw(frame)
        step_ms += (time.perf_counter() - t0) * 1000
        seq, n = (seq + 1) & 0xFF, n + 1
        if args.stats and now - report >= 5:
            s = engine.stats
            print(f"{n} frames: python+submit {step_ms / n:.1f} ms/frame, last frame {s['frame_ms']:.1f} ms, "
                  f"{s['instances']} instances ({s['culled']} culled), {s['triangles']} triangles", flush=True)
            report = now
        if args.frames and n >= args.frames:
            break
    if args.shot:
        engine.screenshot(args.shot)
    music.close()
    engine.close()


if __name__ == "__main__":
    main()
