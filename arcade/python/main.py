"""Game loop on the UNO Q MPU: game logic in Python, rendering on the MCU (docs/api.md)."""

import time

from arduino.app_utils import App, Bridge

import g3d
import world
from game import Game

FRAME_PERIOD = 0.05     # s; ~20 packets/s keeps ahead of the MCU's ~15 fps without flooding Bridge
MAX_DT = 0.1            # s; clamp long stalls so the game does not jump
RECONNECT_FAILURES = 10  # api.md §4: re-run hello and the scene upload

link = g3d.G3D(Bridge.call)
scene = world.make_scene(seed=1)
game = Game(scene)
state = {"connected": False, "raw": None, "seq": 0, "last": time.monotonic()}


def connect():
    caps = link.hello()
    link.load_scene(scene)
    link.failures = 0
    state["connected"] = True
    print(f"g3d connected: {caps}")


def loop():
    if not state["connected"]:
        try:
            connect()
        except Exception as error:
            print(f"g3d connect failed: {error}")
            time.sleep(1)
        state["last"] = time.monotonic()
        return
    start = time.monotonic()
    dt = min(start - state["last"], MAX_DT)
    state["last"] = start
    cam, objs, hud, flags = game.step(state["raw"], dt)
    state["raw"] = link.frame(g3d.pack_frame(state["seq"], cam, objs, hud, flags=flags))
    state["seq"] = (state["seq"] + 1) & 0xFF
    if link.failures >= RECONNECT_FAILURES:
        print("g3d: no replies, reconnecting")
        state["connected"] = False
        return
    time.sleep(max(0.0, FRAME_PERIOD - (time.monotonic() - start)))


print("Arcade 3D: stick to move, tilt to look, B to shoot, A for the menu.")
App.run(user_loop=loop)
