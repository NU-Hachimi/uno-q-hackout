"""The PC: walking on the terrain, kept out of the boss's feet, and hitscan shooting."""

import math
import random
from dataclasses import dataclass

import camera
import collide
import g3d
import rig
import world
from gen import mesh_ids, palette

SPEED = 6.0             # m/s at full stick
TURN_RATE = 10.0        # rad/s the model turns towards its heading
EDGE_MARGIN = 10.0      # m kept from the map edge
HP_MAX = 5

SHOT_COOLDOWN = 0.25    # s
SHOT_RANGE = 80.0       # m
TRACER_SPEED = 120.0    # m/s; the hit lands when the streak arrives
MAX_TRACERS = 3
GROUND_STEP = 1.0       # m between terrain samples along a shot
MAX_SPARKS = 6
HIT_SPARK_LIFE = 0.25   # s
DEBRIS_LIFE = 0.6       # s
DEBRIS_COUNT = 6
GRAVITY = 9.8
INVULNERABLE = 1.0      # s after being hit
HURT_FLASH = 0.3        # s of red screen after being hit

HOOK_RANGE = 25.0       # m from the hand
HOOK_FLIGHT = 0.3       # s for the hook to reach its point, or to come back after a miss
HOOK_PULL_SPEED = 15.0  # m/s
HOOK_ARRIVE = 0.5       # m; closer than this to the anchor counts as hooked on
HOOK_SCALE = 1.5

# Hook states
FLYING, RETURNING, PULLING, HOOKED = "flying", "returning", "pulling", "hooked"


@dataclass
class Tracer:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    life: float          # s until it reaches its end point
    slot: int = -1       # boss part to damage on arrival, -1 for none
    damage: int = 1
    hooked: bool = False
    tint: int = 0        # spark colour on arrival


@dataclass
class Spark:
    x: float
    y: float
    z: float
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    age: float = 0.0
    life: float = HIT_SPARK_LIFE
    tint: int = 0
    falls: bool = False


def _wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


class Player:
    def __init__(self, scene, x=0.0, z=-30.0, yaw=0.0, seed=None):
        self.scene = scene
        self.x, self.z, self.yaw = x, z, yaw
        self.y = world.terrain_height(scene, x, z)
        self.hp = HP_MAX
        self.cooldown = 0.0
        self.tracers = []
        self.sparks = []
        self.hook = None       # FLYING / RETURNING / PULLING / HOOKED, or None
        self.hook_bone = -1    # boss bone the hook holds, with the anchor in that bone's frame
        self.hook_local = (0.0, 0.0, 0.0)
        self.hook_from = (0.0, 0.0, 0.0)  # hand position when fired
        self.hook_to = (0.0, 0.0, 0.0)    # world point the hook flies to
        self.hook_head = (0.0, 0.0, 0.0)  # where the hook head is drawn while flying
        self.hook_time = 0.0
        self.vy = 0.0
        self.airborne = False  # falling after letting go
        self.invulnerable = 0.0
        self.hurt_flash = 0.0
        self.shots = 0  # fired so far this round
        self.queued = False  # a B tap during the cooldown fires as soon as it ends
        self.rng = random.Random(seed)

    def hand(self):
        """World position of the `hand` attachment (shots and the rope start here)."""
        hx, hy, hz = mesh_ids.PC_HAND
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return self.x + hx * c + hz * s, self.y + hy, self.z - hx * s + hz * c

    @property
    def hooked(self):
        return self.hook == HOOKED

    def update(self, inp, cam, dt, boss, aim, colliders):
        """C fires or releases the hook; the stick walks (on the ground only); B shoots along `aim`."""
        self.invulnerable = max(0.0, self.invulnerable - dt)
        self.hurt_flash = max(0.0, self.hurt_flash - dt)
        if inp.pressed & g3d.BTN_C:
            self._hook_button(aim)
        if self.hook in (PULLING, HOOKED):
            pass  # carried by the hook
        elif self.airborne:
            self._fall(dt)
        else:
            self._walk(inp, cam, dt, boss)
        self._update_hook(dt, boss)

        self.cooldown = max(0.0, self.cooldown - dt)
        # Holding B fires at the cooldown rate; a tap shorter than a frame only shows in `pressed`,
        # and a tap during the cooldown is kept until it ends.
        self.queued = self.queued or bool(inp.pressed & g3d.BTN_B)
        if (self.queued or inp.held & g3d.BTN_B) and self.cooldown <= 1e-6 and len(self.tracers) < MAX_TRACERS:
            self.queued = False
            self._shoot(aim, colliders)
        self._advance(dt, boss)

    def _walk(self, inp, cam, dt, boss):
        f, r = camera.forward(cam.yaw), camera.right(cam.yaw)
        mx = f[0] * inp.move_y + r[0] * inp.move_x
        mz = f[2] * inp.move_y + r[2] * inp.move_x
        if math.hypot(mx, mz) > 1e-3:
            lo, hi = world.extent(self.scene, EDGE_MARGIN)
            self.x = min(hi, max(lo, self.x + mx * SPEED * dt))
            self.z = min(hi, max(lo, self.z + mz * SPEED * dt))
            self._face(math.atan2(mx, mz), dt)
        for _ in range(2):  # twice, in case pushing out of one foot lands inside another
            for cx, cz, radius in boss.feet():
                self.x, self.z = collide.push_out(self.x, self.z, cx, cz, radius)
        self.y = world.terrain_height(self.scene, self.x, self.z)

    def _fall(self, dt):
        self.vy -= GRAVITY * dt
        self.y += self.vy * dt
        ground = world.terrain_height(self.scene, self.x, self.z)
        if self.y <= ground:
            self.y, self.vy, self.airborne = ground, 0.0, False

    # ---- hook -------------------------------------------------------------------------------
    def _hook_button(self, aim):
        if self.hook in (PULLING, HOOKED):  # let go and drop
            self.hook, self.airborne, self.vy = None, True, 0.0
            return
        if self.hook is not None or self.airborne:
            return
        self.hook_from = self.hand()
        self.hook_head = self.hook_from
        self.hook_time = 0.0
        self.hook = FLYING
        if aim.hook is not None:
            self.hook_bone = aim.hook.collider.bone
            self.hook_to = aim.hook.point
            self.hook_local = None  # resolved against the bone when the hook lands
            self.yaw = math.atan2(self.hook_to[0] - self.x, self.hook_to[2] - self.z)
        else:
            self.hook_bone = -1
            d = aim.direction
            self.hook_to = tuple(a + b * HOOK_RANGE for a, b in zip(self.hook_from, d))
            self.yaw = math.atan2(d[0], d[2])

    def anchor(self, boss):
        """World position of the hook's anchor on the boss (it moves with the bone)."""
        bones, _ = boss.poses()
        return rig.transform(bones[self.hook_bone], self.hook_local)

    def _update_hook(self, dt, boss):
        if self.hook is None:
            return
        self.hook_time += dt
        t = min(1.0, self.hook_time / HOOK_FLIGHT)
        if self.hook == FLYING:
            self.hook_head = tuple(a + (b - a) * t for a, b in zip(self.hook_from, self.hook_to))
            if t >= 1.0:
                if self.hook_bone >= 0:
                    bones, _ = boss.poses()
                    self.hook_local = rig.transform(rig.inverse(bones[self.hook_bone]), self.hook_to)
                    self.hook = PULLING
                else:
                    self.hook, self.hook_time = RETURNING, 0.0
        elif self.hook == RETURNING:
            self.hook_head = tuple(b + (a - b) * t for a, b in zip(self.hand(), self.hook_to))
            if t >= 1.0:
                self.hook = None
        else:
            target = self.anchor(boss)
            if self.hook == PULLING:
                d = tuple(b - a for a, b in zip((self.x, self.y, self.z), target))
                dist = math.sqrt(sum(c * c for c in d))
                step = HOOK_PULL_SPEED * dt
                if dist <= max(HOOK_ARRIVE, step):
                    self.hook = HOOKED
                else:
                    self.x, self.y, self.z = (p + c / dist * step for p, c in zip((self.x, self.y, self.z), d))
                    self.yaw = math.atan2(d[0], d[2])
            if self.hook == HOOKED:
                self.x, self.y, self.z = target
            self.hook_head = target

    def hook_block(self):
        """api.md §3.3 Hook block: bit0 rope visible, bit1 hooked on; anchor = the hook head."""
        if self.hook is None:
            return g3d.Hook()
        return g3d.Hook(flags=1 | (2 if self.hook == HOOKED else 0), x=self.hook_head[0], y=self.hook_head[1],
                        z=self.hook_head[2])

    def hurt(self, damage):
        """A boss attack connected. Ignored while invulnerable or riding the hook."""
        if self.invulnerable > 0 or self.hook in (PULLING, HOOKED) or self.hp <= 0:
            return False
        self.hp = max(0, self.hp - damage)
        self.invulnerable, self.hurt_flash = INVULNERABLE, HURT_FLASH
        return True

    def _face(self, heading, dt):
        step = TURN_RATE * dt
        delta = _wrap(heading - self.yaw)
        self.yaw = _wrap(self.yaw + max(-step, min(step, delta)))

    def _ground_t(self, o, d, limit):
        t = GROUND_STEP
        while t < limit:
            if o[1] + d[1] * t <= world.terrain_height(self.scene, o[0] + d[0] * t, o[2] + d[2] * t):
                return t
            t += GROUND_STEP
        return None

    def _shoot(self, aim, colliders):
        """Resolve the shot now (hitscan) and send a tracer from the hand to where it lands."""
        o, d = aim.origin, aim.direction
        hit = collide.ray_cast(o, d, colliders, SHOT_RANGE)
        ground = self._ground_t(o, d, hit.t if hit else SHOT_RANGE)
        slot, tint = -1, palette.DUST
        if ground is not None:
            end = tuple(a + b * ground for a, b in zip(o, d))
        elif hit is not None:
            end = hit.point
            if hit.collider.kind == "part":
                slot, tint = hit.collider.slot, palette.SPARK
        else:
            end = tuple(a + b * SHOT_RANGE for a, b in zip(o, d))
            tint = 0
        self.yaw = math.atan2(d[0], d[2])  # turn to face the shot
        x, y, z = self.hand()
        v = (end[0] - x, end[1] - y, end[2] - z)
        dist = max(1e-3, math.sqrt(sum(c * c for c in v)))
        speed = TRACER_SPEED / dist
        self.tracers.append(Tracer(x, y, z, v[0] * speed, v[1] * speed, v[2] * speed, dist / TRACER_SPEED,
                                   slot, 2 if self.hooked else 1, self.hooked, tint))
        self.cooldown = SHOT_COOLDOWN
        self.shots += 1

    def _advance(self, dt, boss):
        flying = []
        for t in self.tracers:
            step = min(dt, t.life)
            t.x, t.y, t.z = t.x + t.vx * step, t.y + t.vy * step, t.z + t.vz * step
            t.life -= dt
            if t.life > 0:
                flying.append(t)
                continue
            if t.slot >= 0:
                boss.damage(t.slot, t.damage, t.hooked)
            if t.tint:
                self._add_spark(Spark(t.x, t.y, t.z, tint=t.tint))
        self.tracers = flying
        for s in self.sparks:
            s.age += dt
            s.x, s.y, s.z = s.x + s.vx * dt, s.y + s.vy * dt, s.z + s.vz * dt
            if s.falls:
                s.vy -= GRAVITY * dt
        self.sparks = [s for s in self.sparks if s.age < s.life]

    def _add_spark(self, spark):
        self.sparks = (self.sparks + [spark])[-MAX_SPARKS:]

    def debris(self, pos, tint):
        """A broken part bursts into falling fragments (art.md §6)."""
        for _ in range(DEBRIS_COUNT):
            a = self.rng.uniform(0, 2 * math.pi)
            speed = self.rng.uniform(2.0, 5.0)
            self._add_spark(Spark(pos[0], pos[1], pos[2], math.cos(a) * speed, self.rng.uniform(2.0, 6.0),
                                  math.sin(a) * speed, life=DEBRIS_LIFE, tint=tint, falls=True))

    def objects(self):
        objs = [g3d.Obj(mesh_ids.PC, self.x, self.y, self.z, yaw=self.yaw)]
        if self.hook in (FLYING, RETURNING):
            d = tuple(b - a for a, b in zip(self.hook_from, self.hook_to))
            objs.append(g3d.Obj(mesh_ids.HOOK_HEAD, *self.hook_head, yaw=math.atan2(d[0], d[2]),
                                pitch=-math.atan2(d[1], math.hypot(d[0], d[2])), scale=HOOK_SCALE))
        for t in self.tracers:
            horizontal = math.hypot(t.vx, t.vz)
            objs.append(g3d.Obj(mesh_ids.BULLET, t.x, t.y, t.z, yaw=math.atan2(t.vx, t.vz),
                                pitch=-math.atan2(t.vy, horizontal), scale=3.0))  # long streak: readable at 240x160
        for s in self.sparks:
            grow = 1.0 + (1.0 if s.falls else 3.0) * s.age / s.life
            objs.append(g3d.Obj(mesh_ids.SPARK, s.x, s.y, s.z, yaw=s.age * 20, scale=grow * (3.0 if s.falls else 1.0),
                                tint=s.tint))
        return objs
