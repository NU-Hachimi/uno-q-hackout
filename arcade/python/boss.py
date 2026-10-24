"""Placeholder boss until card B7 (tasks.md): stands in the arena, turns to face the PC and
cycles through every moose animation, so the rig can be seen on the board. No AI, no damage."""

import math

import g3d
import world
from gen import rigs as gen_rigs

MOOSE = gen_rigs.RIGS[gen_rigs.MOOSE]
SHOWCASE = ("idle", "walk", "punch_r", "sweep", "rear_stomp", "shake", "kneel", "rise")
SHOW_SECONDS = 3.0
TURN_RATE = 0.5  # rad/s


class Boss:
    def __init__(self, scene, x=0.0, z=14.0):
        self.x, self.z = x, z
        self.y = world.terrain_height(scene, x, z)
        self.yaw = math.pi  # facing -Z, towards the PC's start
        self.time = 0.0
        self.part_alive = (1 << len(MOOSE["slots"])) - 1

    def update(self, player, dt):
        self.time += dt
        want = math.atan2(player.x - self.x, player.z - self.z)
        delta = (want - self.yaw + math.pi) % (2 * math.pi) - math.pi
        self.yaw += max(-TURN_RATE * dt, min(TURN_RATE * dt, delta))

    def rig(self):
        name = SHOWCASE[int(self.time / SHOW_SECONDS) % len(SHOWCASE)]
        anim = gen_rigs.ANIM["moose"][name]
        t = (self.time % SHOW_SECONDS) / SHOW_SECONDS
        phase = int(t * 512) & 255 if MOOSE["anims"][anim]["loop"] else int(t * 255)
        return g3d.Rig(gen_rigs.MOOSE, anim, phase, x=self.x, y=self.y, z=self.z, yaw=self.yaw,
                       part_alive=self.part_alive)
