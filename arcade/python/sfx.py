"""Megalith's sound effects on alia-engine's mixer (its docs/api.md §7). The gameplay only notes what
happened where (Player.sounds, Boss.sounds, gathered in Game.sounds each step); this plays them from the
camera's point of view: panned by where they are, quieter with distance, a little pitch variation so
repeats don't sound mechanical. The sounds are made by tools/sfx_build.py."""

import math
import random
from pathlib import Path

import camera

FOLDER = Path(__file__).resolve().parent / "sfx"
LEVELS = {"shot": 0.55, "hit": 0.7, "ground": 0.5, "break": 1.0, "stomp": 1.0, "hook_fire": 0.6,
          "hook_catch": 0.8, "hurt": 0.9}
NEAR = 8.0       # m: full level this close; beyond, it falls off as NEAR / distance
FAR = 120.0      # m: the fog's end; nothing heard beyond
PITCH = 0.06     # +- random pitch per play


class Effects:
    def __init__(self, engine, folder=FOLDER):
        self.audio = engine.audio
        folder = Path(folder)
        self.sounds = {name: self.audio.load(str(folder / f"{name}.wav")) for name in LEVELS
                       if (folder / f"{name}.wav").exists()}
        self.rng = random.Random(1)

    def play(self, events, view):
        """events: [(name, (x, y, z))]; view: the camera (x, y, z, yaw) they are heard from."""
        right = camera.right(view.yaw)
        for name, pos in events:
            sound = self.sounds.get(name)
            if sound is None:
                continue
            d = (pos[0] - view.x, pos[1] - view.y, pos[2] - view.z)
            dist = math.sqrt(sum(c * c for c in d))
            if dist > FAR:
                continue
            gain = LEVELS[name] * min(1.0, NEAR / max(dist, 1e-3))
            pan = sum(a * b for a, b in zip(d, right)) / dist * 0.8 if dist > 1e-3 else 0.0  # never hard left/right
            self.audio.play(sound, volume=gain, pan=pan, pitch=1.0 + self.rng.uniform(-PITCH, PITCH))
