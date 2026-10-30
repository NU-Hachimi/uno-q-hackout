"""The PC: riding over the terrain, kept out of the boss's feet, hitscan shooting and the hook.

Drawn as two rigs (api.md §3.3): the horse, and the rider on the horse's `saddle` attach. The rider
leaves the saddle for the hook; the horse then fades into the fog, and fades back in under the rider
just before touchdown, so the rider lands straight in the saddle (art.md §2).

The PC point (x, y, z) is the horse's hooves while riding or falling, and the rider's feet while the
hook pulls it in or it clings to the boss (standing on the anchor, as before the horse).

Both rigs are the player's own nodes in alia-engine's world, placed and posed every step; the saddle and
the hand are read back from them.
"""

import math
import random
from dataclasses import dataclass

import alia_engine as ae

import assets
import camera
import collide
import controls
import screen
import tilt_config as tilt
import world
from gen import mesh_ids, palette
from gen.rigs import RIGS

SPEED = 6.0             # m/s at full stick
EDGE_MARGIN = 10.0      # m kept from the map edge
HP_MAX = 5

SHOT_COOLDOWN = 0.25    # s
SHOT_RANGE = 80.0       # m
TRACER_SPEED = 120.0    # m/s; the hit lands when the streak arrives
MAX_TRACERS = 3
DEBRIS_COUNT = 6        # fragments when a part breaks (effects.py "debris")
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

HORSE_ID, RIDER_ID = 3, 4
HORSE, RIDER = RIGS[HORSE_ID], RIGS[RIDER_ID]
HORSE_ANIM = {a["name"]: a["id"] for a in HORSE["anims"]}
RIDER_ANIM = {a["name"]: a["id"] for a in RIDER["anims"]}
GALLOP_RATE = 560.0     # gallop phase units per second at full stick (one stride is 256)
TURN_GAIT = 0.35        # gait while turning on the spot, as a fraction of a full gallop
STAND_RATE = 64.0       # phase units per second of the standing loop (4 s)
SHOOT_ANIM = 0.45       # s the rider spends in ride_shoot / hang_shoot after a shot
HIT_ANIM = 0.5          # s of ride_hit (and the horse's hit) after being hurt
LAND_ANIM = 0.35        # s of land_ride after touchdown
FADE_OUT = 0.45         # s for the riderless horse to fade into the fog
FADE_IN = 0.4           # s before touchdown that the horse fades back in under the rider
RIDER_ROOT_Y = RIDER["bones"][0]["offset"][1]
SADDLE_TILT = True      # mounted, the rider hangs on the saddle (and leans with the horse's back); False: upright above it


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


def _wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


class Player:
    def __init__(self, scene, w, x=0.0, z=-30.0, yaw=0.0, seed=None):
        """`w`: the alia_engine.World the horse and the rider live in (assets.load() first)."""
        self.scene = scene
        self.w = w
        self.x, self.z, self.yaw = x, z, yaw
        self.y = world.terrain_height(scene, x, z)
        self.hp = HP_MAX
        self.cooldown = 0.0
        self.tracers = []
        self.sounds = []       # (name, position) this step, for sfx.py; Game.step clears and collects them
        self.hook = None       # FLYING / RETURNING / PULLING / HOOKED, or None
        self.hook_anchor = None  # the boss's hook point node the hook holds (it moves with the bone), if any
        self.hook_from = (0.0, 0.0, 0.0)  # hand position when fired
        self.hook_to = (0.0, 0.0, 0.0)    # world point the hook flies to
        self.hook_head = (0.0, 0.0, 0.0)  # where the hook head is drawn while flying
        self.hook_time = 0.0
        self.vx = self.vy = self.vz = 0.0
        self.airborne = False  # falling after letting go or being thrown off
        self.invulnerable = 0.0
        self.hurt_flash = 0.0
        self.shots = 0  # fired so far this round
        self.queued = False  # a B tap during the cooldown fires as soon as it ends
        self.rng = random.Random(seed)
        self.steer = 0.0         # rad turned by the stick this frame; the camera turns with it
        self.speed = 0.0         # throttle, -REVERSE_FRACTION..1
        self.boost = 1.0         # speed multiplier; the intro gallops faster than the player can
        self.gait = 0.0          # gallop phase, 0..256
        self.standing = True     # stick released: the horse plays `stand`
        self.stand_time = 0.0
        self.since_shot = self.since_hit = self.since_land = 10.0
        self.anim_override = None  # (anim, phase) for the rider while finisher.py runs the finisher
        self.loose = None        # (x, y, z, yaw, speed) of the riderless horse as the rider left it
        self.loose_time = 0.0
        horse, rider = assets.RIGS[HORSE["name"]], assets.RIGS[RIDER["name"]]
        # Rider origin above the hooves while mounted on a standing horse; a falling PC keeps this offset.
        self.mount_drop = horse.attach_position("saddle", HORSE_ANIM["stand"], 0)[1] - RIDER_ROOT_Y
        self.horse, self.rider = w.spawn_rig(horse), w.spawn_rig(rider)
        for node in (self.horse, self.rider):
            node.set_subtree(light=ae.Light.CHARACTER)
        self.saddle, self.hand_point = self.horse.attach_point("saddle"), self.rider.attach_point("hand")
        # Sparks where shots land, debris of broken parts, the finisher's sparks: particles (effects.py).
        seed = self.rng.randrange(1 << 30)
        self.hits, self.debris_fx, self.orbs = (w.spawn_emitter(assets.PARTICLES[name], seed=seed + k)
                                                for k, name in enumerate(("hit", "debris", "orbs")))
        self._horse_fade = 0.0
        self._on_saddle = False
        self.present()
        for node in (self.horse, self.rider):
            node.teleport()  # spawned at the origin: no slide from there

    def close(self):
        """Take the horse and the rider out of the world (a new round makes a new PC)."""
        for node in (self.horse, self.rider, self.hits, self.debris_fx, self.orbs):
            if node.alive:
                node.destroy()

    @property
    def hooked(self):
        return self.hook == HOOKED

    @property
    def on_boss(self):
        """Pulled in by the hook or clinging to the brow."""
        return self.hook in (PULLING, HOOKED)

    @property
    def mounted(self):
        return self.hook not in (PULLING, HOOKED) and not self.airborne

    def _horse_anim(self):
        if self.since_hit < HIT_ANIM:
            return HORSE_ANIM["hit"], int(255 * self.since_hit / HIT_ANIM)
        if self.standing:
            return HORSE_ANIM["stand"], int(self.stand_time * STAND_RATE) & 255
        return HORSE_ANIM["gallop"], int(self.gait) & 255

    def _rider_anim(self):
        if self.anim_override:
            return self.anim_override
        shooting = self.since_shot < SHOOT_ANIM
        shot = int(255 * self.since_shot / SHOOT_ANIM)
        if self.hook == PULLING:
            return RIDER_ANIM["hook_pull"], int(self.hook_time * 400) & 255
        if self.hook == HOOKED:
            return (RIDER_ANIM["cling_shoot"], shot) if shooting else (RIDER_ANIM["cling"], int(self.hook_time * 64) & 255)
        if self.airborne:
            return RIDER_ANIM["fall"], int(self.loose_time * 400) & 255
        if self.hook in (FLYING, RETURNING):
            return RIDER_ANIM["hook_fire"], min(255, int(255 * self.hook_time / HOOK_FLIGHT))
        if self.since_land < LAND_ANIM:
            return RIDER_ANIM["land_ride"], int(255 * self.since_land / LAND_ANIM)
        if self.since_hit < HIT_ANIM:
            return RIDER_ANIM["ride_hit"], int(255 * self.since_hit / HIT_ANIM)
        if shooting:
            return RIDER_ANIM["ride_shoot"], shot
        return RIDER_ANIM["ride"], 0 if self.standing else int(self.gait) & 255

    def _rider_origin(self):
        """World position of the rider rig's origin (yaw is self.yaw)."""
        if self.hook in (PULLING, HOOKED):  # feet on the PC point
            return self.x, self.y, self.z
        if self.airborne:
            return self.x, self.y + self.mount_drop, self.z
        self._place_horse()  # mounted: the horse stands on the PC point
        if SADDLE_TILT:
            self._place_rider()
            return self.rider.world_position
        sx, sy, sz = self.saddle.world_position
        return sx, sy - RIDER_ROOT_Y, sz

    def hand(self):
        """World position of the rider's `hand` attach (shots and the rope start here)."""
        self._place_rider()
        return self.hand_point.world_position

    def _place_horse(self):
        """The horse node follows _horse_block(): out of the world when there is none."""
        block = self._horse_block()
        node = self.horse
        node.active = block is not None
        if block is not None:
            node.position, node.yaw = (block.x, block.y, block.z), block.yaw
            node.animator.anim, node.animator.phase = block.anim, block.phase
            if self._horse_fade != block.fade:
                node.set_subtree(fade=block.fade)
                self._horse_fade = block.fade

    def _place_rider(self):
        node = self.rider
        node.animator.anim, node.animator.phase = self._rider_anim()
        on = SADDLE_TILT and self.mounted
        if on != self._on_saddle:  # mounting or leaving: stay put in the world, so the step still blends
            node.set_parent(self.saddle if on else None, keep_world=True)
            self._on_saddle = on
        if on:  # the root bone on the saddle; the horse's heading and lean come from the parent
            self._place_horse()
            node.position, node.rotation = (0.0, -RIDER_ROOT_Y, 0.0), (0.0, 0.0, 0.0, 1.0)
        else:
            node.position, node.yaw = self._rider_origin(), self.yaw

    def present(self):
        """Once a step: the horse and the rider show this step's state."""
        self._place_horse()
        self._place_rider()

    def update(self, inp, cam, dt, boss, aim):
        """C fires or releases the hook; the stick walks (on the ground only); B shoots along `aim`."""
        self.invulnerable = max(0.0, self.invulnerable - dt)
        self.hurt_flash = max(0.0, self.hurt_flash - dt)
        self.steer = 0.0
        self.since_shot += dt
        self.since_hit += dt
        self.since_land += dt
        self.loose_time += dt
        if inp.pressed & controls.BTN_C:
            self._hook_button(aim, boss)
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
        self.queued = self.queued or bool(inp.pressed & controls.BTN_B)
        if (self.queued or inp.held & controls.BTN_B) and self.cooldown <= 1e-6 and len(self.tracers) < MAX_TRACERS:
            self.queued = False
            self._shoot(aim, boss)
        self._advance(dt, boss)

    def _walk(self, inp, cam, dt, boss):
        """Ride: stick x steers (the camera follows through self.steer), stick y is the throttle."""
        self.steer = -inp.move_x * math.radians(tilt.STEER_RATE_DEG) * dt  # turning right lowers yaw
        self.yaw = _wrap(self.yaw + self.steer)
        self.speed = inp.move_y if inp.move_y >= 0 else inp.move_y * tilt.REVERSE_FRACTION
        if abs(self.speed) > 1e-3:
            f = camera.forward(self.yaw)
            lo, hi = world.extent(self.scene, EDGE_MARGIN)
            self.x = min(hi, max(lo, self.x + f[0] * self.speed * SPEED * self.boost * dt))
            self.z = min(hi, max(lo, self.z + f[2] * self.speed * SPEED * self.boost * dt))
        gait = max(abs(self.speed) * self.boost, TURN_GAIT * abs(inp.move_x))
        self.standing = gait < 0.05
        if self.standing:
            self.stand_time += dt
        else:
            self.gait = (self.gait + math.copysign(GALLOP_RATE * gait * dt, self.speed or 1.0)) % 256
        for _ in range(2):  # twice, in case pushing out of one foot lands inside another
            for cx, cz, radius in boss.feet():
                self.x, self.z = collide.push_out(self.x, self.z, cx, cz, radius)
        self.y = world.terrain_height(self.scene, self.x, self.z)

    def _fall(self, dt):
        lo, hi = world.extent(self.scene, EDGE_MARGIN)
        self.x = min(hi, max(lo, self.x + self.vx * dt))
        self.z = min(hi, max(lo, self.z + self.vz * dt))
        self.vy -= GRAVITY * dt
        self.y += self.vy * dt
        ground = world.terrain_height(self.scene, self.x, self.z)
        if self.y <= ground:
            self.y, self.airborne = ground, False
            self.vx = self.vy = self.vz = 0.0
            self.since_land, self.loose = 0.0, None  # straight into the saddle

    # ---- hook -------------------------------------------------------------------------------
    def _hook_button(self, aim, boss):
        if self.hook in (PULLING, HOOKED):  # let go and drop; from here the PC point is the hooves again
            ox, oy, oz = self._rider_origin()
            self.x, self.y, self.z = ox, oy - self.mount_drop, oz
            self.hook, self.airborne, self.loose_time = None, True, 0.0
            self.vx = self.vy = self.vz = 0.0
            return
        if self.hook is not None or self.airborne:
            return
        self.hook_from = self.hand()
        self.hook_head = self.hook_from
        self.hook_time = 0.0
        self.hook = FLYING
        self.sounds.append(("hook_fire", self.hook_from))
        if aim.hook is not None:
            self.hook_anchor = aim.hook.collider.node  # rides the bone, so the hook lands on the brow wherever it moved
            self.hook_to = aim.hook.point
            self.yaw = math.atan2(self.hook_to[0] - self.x, self.hook_to[2] - self.z)
        else:
            self.hook_anchor = None
            d = aim.direction
            self.hook_to = tuple(a + b * HOOK_RANGE for a, b in zip(self.hook_from, d))
            self.yaw = math.atan2(d[0], d[2])

    def anchor(self, boss):
        """World position of the hook's anchor on the boss (it moves with the bone)."""
        return boss.position_of(self.hook_anchor)

    def _update_hook(self, dt, boss):
        if self.hook is None:
            return
        self.hook_time += dt
        t = min(1.0, self.hook_time / HOOK_FLIGHT)
        if self.hook == FLYING:
            if self.hook_anchor is not None:
                self.hook_to = self.anchor(boss)
            self.hook_head = tuple(a + (b - a) * t for a, b in zip(self.hook_from, self.hook_to))
            if t >= 1.0:
                if self.hook_anchor is not None:
                    # The rider leaves the saddle: the horse runs on and fades out; the PC point becomes the feet.
                    self.loose, self.loose_time = (self.x, self.y, self.z, self.yaw, max(self.speed, 0.6)), 0.0
                    self.x, self.y, self.z = self._rider_origin()
                    self.hook = PULLING
                    self.sounds.append(("hook_catch", self.hook_to))
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
            return screen.Hook()
        return screen.Hook(flags=1 | (2 if self.hook == HOOKED else 0), x=self.hook_head[0], y=self.hook_head[1],
                        z=self.hook_head[2])

    def thrown(self, away, damage, speed=7.0, up=5.0):
        """The boss shook the PC off: it flies away from the boss (horizontal unit `away`) and falls back
        into the saddle like after letting go (art.md §2), with a hit that ignores hooked immunity."""
        if self.hook not in (PULLING, HOOKED):
            return False
        ox, oy, oz = self._rider_origin()
        self.x, self.y, self.z = ox, oy - self.mount_drop, oz
        self.hook, self.airborne, self.loose_time = None, True, 0.0
        self.vx, self.vy, self.vz = away[0] * speed, up, away[1] * speed
        self.hp = max(0, self.hp - damage)
        self.invulnerable, self.hurt_flash, self.since_hit = INVULNERABLE, HURT_FLASH, 0.0
        self.sounds.append(("hurt", (self.x, self.y, self.z)))
        return True

    def hurt(self, damage):
        """A boss attack connected. Ignored while invulnerable or riding the hook."""
        if self.invulnerable > 0 or self.hook in (PULLING, HOOKED) or self.hp <= 0:
            return False
        self.hp = max(0, self.hp - damage)
        self.invulnerable, self.hurt_flash, self.since_hit = INVULNERABLE, HURT_FLASH, 0.0
        self.sounds.append(("hurt", (self.x, self.y, self.z)))
        return True

    def _shoot(self, aim, boss):
        """Resolve the shot now (hitscan) and send a tracer from the hand to where it lands: the boss, the
        ground (alia-engine's, from the same terrain) or nothing."""
        o, d = aim.origin, aim.direction
        hit = boss.ray_cast(o, d, SHOT_RANGE)
        ground = boss.w.ray_ground(o, d, hit.t if hit else SHOT_RANGE)
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
        x, y, z = self.hand()  # the horse keeps its heading; only the shot goes to the reticle
        v = (end[0] - x, end[1] - y, end[2] - z)
        dist = max(1e-3, math.sqrt(sum(c * c for c in v)))
        speed = TRACER_SPEED / dist
        self.tracers.append(Tracer(x, y, z, v[0] * speed, v[1] * speed, v[2] * speed, dist / TRACER_SPEED,
                                   slot, 2 if self.hooked else 1, self.hooked, tint))
        self.cooldown = SHOT_COOLDOWN
        self.sounds.append(("shot", (x, y, z)))
        self.shots += 1
        self.since_shot = 0.0

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
                self.hits.burst(1, at=(t.x, t.y, t.z), tint=t.tint)
                self.sounds.append(("hit" if t.slot >= 0 else "ground", (t.x, t.y, t.z)))  # sparks off a part, else dust
        self.tracers = flying

    def debris(self, pos, tint):
        """A broken part bursts into falling fragments (art.md §6)."""
        self.debris_fx.burst(DEBRIS_COUNT, at=pos, tint=tint)

    def _horse_block(self):
        """The horse: under the rider, fading out after the rider left it, or fading in before touchdown."""
        if self.mounted:
            return screen.Rig(HORSE_ID, *self._horse_anim(), x=self.x, y=self.y, z=self.z, yaw=self.yaw, char_light=True)
        if self.airborne:  # time to land under gravity, from y + vy t - g t^2 / 2 = ground
            drop = self.y - world.terrain_height(self.scene, self.x, self.z)
            t = (self.vy + math.sqrt(self.vy * self.vy + 2 * GRAVITY * max(drop, 0.0))) / GRAVITY
            if t < FADE_IN:
                ground = self.y - drop
                return screen.Rig(HORSE_ID, HORSE_ANIM["gallop"], int(self.loose_time * GALLOP_RATE) & 255,
                               x=self.x, y=ground, z=self.z, yaw=self.yaw, char_light=True, fade=t / FADE_IN)
        if self.loose and self.loose_time < FADE_OUT:
            x, y, z, yaw, speed = self.loose
            d = speed * SPEED * self.loose_time
            x, z = x + math.sin(yaw) * d, z + math.cos(yaw) * d
            return screen.Rig(HORSE_ID, HORSE_ANIM["gallop"], int(self.loose_time * GALLOP_RATE) & 255,
                           x=x, y=world.terrain_height(self.scene, x, z), z=z, yaw=yaw, char_light=True,
                           fade=self.loose_time / FADE_OUT)
        return None

    def rigs(self):
        """[horse or None, rider] rig blocks, both under the character light."""
        rider = screen.Rig(RIDER_ID, *self._rider_anim(), x=0, y=0, z=0, yaw=self.yaw, char_light=True)
        rider.x, rider.y, rider.z = self._rider_origin()
        return [self._horse_block(), rider]

    def objects(self):
        objs = []
        if self.hook in (FLYING, RETURNING):
            d = tuple(b - a for a, b in zip(self.hook_from, self.hook_to))
            objs.append(screen.Obj(mesh_ids.HOOK_HEAD, *self.hook_head, yaw=math.atan2(d[0], d[2]),
                                pitch=-math.atan2(d[1], math.hypot(d[0], d[2])), scale=HOOK_SCALE))
        for t in self.tracers:
            horizontal = math.hypot(t.vx, t.vz)
            objs.append(screen.Obj(mesh_ids.BULLET, t.x, t.y, t.z, yaw=math.atan2(t.vx, t.vz),
                                pitch=-math.atan2(t.vy, horizontal), scale=3.0))  # long streak: readable at 240x160
        return objs
