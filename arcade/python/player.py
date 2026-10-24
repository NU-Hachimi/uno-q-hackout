"""The PC: walking on the terrain and shooting along the reticle."""

import math
from dataclasses import dataclass

import camera
import g3d
import world
from gen import mesh_ids

SPEED = 6.0             # m/s at full stick
TURN_RATE = 10.0        # rad/s the model turns towards its heading
EDGE_MARGIN = 10.0      # m kept from the map edge
HP_MAX = 5

SHOT_COOLDOWN = 0.25    # s
BULLET_SPEED = 40.0     # m/s
BULLET_LIFE = 0.6       # s
MAX_BULLETS = 4
AIM_RANGE = 60.0        # m; bullets fly towards the reticle point, at most this far
AIM_STEP = 1.0          # m between terrain samples along the reticle ray
SPARK_LIFE = 0.25       # s
MAX_SPARKS = 4


@dataclass
class Bullet:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    age: float = 0.0


@dataclass
class Spark:
    x: float
    y: float
    z: float
    age: float = 0.0


def _wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


class Player:
    def __init__(self, scene, x=0.0, z=-12.0, yaw=0.0):
        self.scene = scene
        self.x, self.z, self.yaw = x, z, yaw
        self.y = world.terrain_height(scene, x, z)
        self.hp = HP_MAX
        self.cooldown = 0.0
        self.bullets = []
        self.sparks = []

    def hand(self):
        """World position of the `hand` attachment (bullets and, later, the rope start here)."""
        hx, hy, hz = mesh_ids.PC_HAND
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return self.x + hx * c + hz * s, self.y + hy, self.z - hx * s + hz * c

    def update(self, inp, cam, view, dt):
        """Move relative to the camera, then advance shots. `view` is this frame's g3d.Camera."""
        f, r = camera.forward(cam.yaw), camera.right(cam.yaw)
        mx = f[0] * inp.move_y + r[0] * inp.move_x
        mz = f[2] * inp.move_y + r[2] * inp.move_x
        speed = math.hypot(mx, mz)
        if speed > 1e-3:
            lo, hi = world.extent(self.scene, EDGE_MARGIN)
            self.x = min(hi, max(lo, self.x + mx * SPEED * dt))
            self.z = min(hi, max(lo, self.z + mz * SPEED * dt))
            self._face(math.atan2(mx, mz), dt)
        self.y = world.terrain_height(self.scene, self.x, self.z)

        self.cooldown = max(0.0, self.cooldown - dt)
        # Holding B fires at the cooldown rate; a tap shorter than a frame only shows in `pressed`.
        if (inp.held | inp.pressed) & g3d.BTN_B and self.cooldown <= 1e-6 and len(self.bullets) < MAX_BULLETS:
            self._shoot(view)
        self._advance(dt)

    def _face(self, heading, dt):
        step = TURN_RATE * dt
        delta = _wrap(heading - self.yaw)
        self.yaw = _wrap(self.yaw + max(-step, min(step, delta)))

    def _aim_point(self, view):
        """Where the reticle ray first meets the terrain, or AIM_RANGE along it."""
        d = camera.forward(view.yaw, view.pitch)
        t = AIM_STEP
        while t < AIM_RANGE:
            x, y, z = view.x + d[0] * t, view.y + d[1] * t, view.z + d[2] * t
            if y <= world.terrain_height(self.scene, x, z):
                return x, y, z
            t += AIM_STEP
        return view.x + d[0] * AIM_RANGE, view.y + d[1] * AIM_RANGE, view.z + d[2] * AIM_RANGE

    def _shoot(self, view):
        d = camera.forward(view.yaw, view.pitch)
        aim = self._aim_point(view)
        self.yaw = math.atan2(d[0], d[2])  # turn to face the shot
        x, y, z = self.hand()
        dx, dy, dz = aim[0] - x, aim[1] - y, aim[2] - z
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        self.bullets.append(Bullet(x, y, z, dx / length * BULLET_SPEED, dy / length * BULLET_SPEED,
                                   dz / length * BULLET_SPEED))
        self.cooldown = SHOT_COOLDOWN

    def _advance(self, dt):
        alive = []
        for b in self.bullets:
            b.age += dt
            b.x, b.y, b.z = b.x + b.vx * dt, b.y + b.vy * dt, b.z + b.vz * dt
            ground = world.terrain_height(self.scene, b.x, b.z)
            if b.y <= ground:
                self._spark(b.x, ground + 0.1, b.z)
            elif b.age < BULLET_LIFE:
                alive.append(b)
        self.bullets = alive
        for s in self.sparks:
            s.age += dt
        self.sparks = [s for s in self.sparks if s.age < SPARK_LIFE]

    def _spark(self, x, y, z):
        self.sparks = (self.sparks + [Spark(x, y, z)])[-MAX_SPARKS:]

    def objects(self):
        objs = [g3d.Obj(mesh_ids.PC, self.x, self.y, self.z, yaw=self.yaw)]
        for b in self.bullets:
            horizontal = math.hypot(b.vx, b.vz)
            objs.append(g3d.Obj(mesh_ids.BULLET, b.x, b.y, b.z, yaw=math.atan2(b.vx, b.vz),
                                pitch=-math.atan2(b.vy, horizontal), scale=3.0))  # long streak: readable at 240x160
        for s in self.sparks:
            grow = 1.0 + 3.0 * s.age / SPARK_LIFE
            objs.append(g3d.Obj(mesh_ids.SPARK, s.x, s.y, s.z, yaw=s.age * 20, scale=grow))
        return objs
