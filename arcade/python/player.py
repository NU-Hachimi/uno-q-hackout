"""The PC: riding the horse over the terrain and shooting along the reticle.

Drawn as two rigs (api.md §3.3): the horse, and the rider sitting on the horse's `saddle` attach.
"""

import math
from dataclasses import dataclass

import camera
import g3d
import rig
import tilt_config as tilt
import world
from gen import mesh_ids
from gen import rigs as gen_rigs

SPEED = 6.0             # m/s at full stick
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

HORSE = gen_rigs.RIGS[gen_rigs.HORSE]
RIDER = gen_rigs.RIGS[gen_rigs.PC]
GALLOP, STAND = gen_rigs.ANIM["horse"]["gallop"], gen_rigs.ANIM["horse"]["stand"]
RIDE, RIDE_SHOOT = gen_rigs.ANIM["pc"]["ride"], gen_rigs.ANIM["pc"]["ride_shoot"]
GALLOP_RATE = 560.0     # phase units per second at full stick (one stride is 256)
TURN_GAIT = 0.35        # gait speed while turning on the spot, as a fraction of a full gallop
STAND_RATE = 64.0       # phase units per second of the standing loop (4 s)
SHOOT_ANIM = 0.45       # s the rider spends in ride_shoot after a shot
RIDER_ROOT_Y = RIDER["bones"][0]["offset"][1]


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
        self.gait = 0.0          # horse gallop phase, 0..256
        self.standing = True     # stick released: the horse plays `stand`
        self.stand_time = 0.0
        self.steer = 0.0         # rad turned this frame by the stick; the camera turns with it
        self.since_shot = SHOOT_ANIM
        self.cooldown = 0.0
        self.bullets = []
        self.sparks = []

    def _horse(self):
        """(anim, phase) of the horse."""
        if self.standing:
            return STAND, int(self.stand_time * STAND_RATE) & 255
        return GALLOP, int(self.gait) & 255

    def _rider(self):
        """(anim, phase) of the rider."""
        if self.since_shot < SHOOT_ANIM:
            return RIDE_SHOOT, int(255 * self.since_shot / SHOOT_ANIM)
        return RIDE, 0 if self.standing else int(self.gait) & 255

    def _rider_origin(self):
        """Rider rig origin: on the horse's saddle, minus the rider root's own offset."""
        sx, sy, sz = rig.attach(HORSE, "saddle", *self._horse(), self.x, self.y, self.z, self.yaw)
        return sx, sy - RIDER_ROOT_Y, sz

    def hand(self):
        """World position of the rider's `hand` attach (bullets and, later, the rope start here)."""
        anim, phase = self._rider()
        return rig.attach(RIDER, "hand", anim, phase, *self._rider_origin(), self.yaw)

    def update(self, inp, cam, view, dt):
        """Ride: stick x steers (the camera follows through self.steer), stick y is the throttle.
        Then advance shots. `view` is this frame's g3d.Camera."""
        self.steer = -inp.move_x * math.radians(tilt.STEER_RATE_DEG) * dt  # turning right lowers yaw
        self.yaw = _wrap(self.yaw + self.steer)
        throttle = inp.move_y if inp.move_y >= 0 else inp.move_y * tilt.REVERSE_FRACTION
        if abs(throttle) > 1e-3:
            f = camera.forward(self.yaw)
            lo, hi = world.extent(self.scene, EDGE_MARGIN)
            self.x = min(hi, max(lo, self.x + f[0] * throttle * SPEED * dt))
            self.z = min(hi, max(lo, self.z + f[2] * throttle * SPEED * dt))
        self.y = world.terrain_height(self.scene, self.x, self.z)
        gait = max(abs(throttle), TURN_GAIT * abs(inp.move_x))
        self.standing = gait < 0.05
        if self.standing:
            self.stand_time += dt
        else:
            self.gait = (self.gait + math.copysign(GALLOP_RATE * gait * dt, throttle or 1.0)) % 256
        self.since_shot += dt

        self.cooldown = max(0.0, self.cooldown - dt)
        # Holding B fires at the cooldown rate; a tap shorter than a frame only shows in `pressed`.
        if (inp.held | inp.pressed) & g3d.BTN_B and self.cooldown <= 1e-6 and len(self.bullets) < MAX_BULLETS:
            self._shoot(view)
        self._advance(dt)

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
        """Shoot at the reticle without turning the horse: the bullet leaves the hand towards the aim point."""
        aim = self._aim_point(view)
        x, y, z = self.hand()
        dx, dy, dz = aim[0] - x, aim[1] - y, aim[2] - z
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        self.bullets.append(Bullet(x, y, z, dx / length * BULLET_SPEED, dy / length * BULLET_SPEED,
                                   dz / length * BULLET_SPEED))
        self.cooldown = SHOT_COOLDOWN
        self.since_shot = 0.0

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

    def rigs(self):
        """[horse, rider] rig blocks, both under the character light."""
        anim, phase = self._rider()
        horse = g3d.Rig(gen_rigs.HORSE, *self._horse(), x=self.x, y=self.y, z=self.z, yaw=self.yaw, char_light=True)
        x, y, z = self._rider_origin()
        rider = g3d.Rig(gen_rigs.PC, anim, phase, x=x, y=y, z=z, yaw=self.yaw, char_light=True)
        return [horse, rider]

    def objects(self):
        objs = []
        for b in self.bullets:
            horizontal = math.hypot(b.vx, b.vz)
            objs.append(g3d.Obj(mesh_ids.BULLET, b.x, b.y, b.z, yaw=math.atan2(b.vx, b.vz),
                                pitch=-math.atan2(b.vy, horizontal), scale=3.0))  # long streak: readable at 240x160
        for s in self.sparks:
            grow = 1.0 + 3.0 * s.age / SPARK_LIFE
            objs.append(g3d.Obj(mesh_ids.SPARK, s.x, s.y, s.z, yaw=s.age * 20, scale=grow))
        return objs
