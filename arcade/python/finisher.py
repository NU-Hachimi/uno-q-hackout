"""The finisher (docs/plan.md): once every part is broken and the weak point is bare, a PC hooked on the
boss's brow is told FINISH HIM (B). Pressing B plays the rider's `execute` animation (art.md §2): it jumps
from the brow onto the weak point, winds up, slams the hook in, twists it twice and pulls it out; the weak
point shatters and the boss dies. When the boss starts to fade, the rider drops back into the saddle the
way it does after letting go.

Timing follows art.md: the rider's root moves from the hook anchor onto the weak point over keys 0-3; the
hit (the first `sparks` event, key 8) freezes for HIT_STOP, and from the hit to the shatter (the second
`sparks` event, key 11) everything runs at SLOW speed: the animation, the boss, the sparks and the debris.
The boss has no `die` animation yet, so it holds its pose (or kneels) and sinks into the fog.
"""

import math

import aim
import assets
import screen
import terrain
from controls import Input
from gen import mesh_ids, palette
from player import RIDER

RIDER_ANIM, BOSS_ANIM = "execute", "die"   # `die` is used once the moose rig has it
EXECUTE_SECONDS = 3.5     # s the whole `execute` animation takes at full speed
LAND_KEY = 3              # the rider stands on the weak point from this key on
SLOW = 0.25               # speed from the hit to the shatter
HIT_STOP = 0.12           # s frozen on the hit
DIE = 2.5                 # s from the shatter to the boss gone
FADE = 1.5                # s at the end of DIE the boss sinks into the fog; the rider lets go as it starts
TAIL = 0.6                # s held on the empty field (with the PC back in the saddle) before the victory screen
FLASH_SECONDS = 0.35      # the big flash on the hand at the hit
FLASH_SCALE = 4.8         # 4 x a spark (effects.py "orbs", size 1.2)
CAMERA_DIST = (8.0, 20.0)  # m from the target, pulling back while the boss dies
CAMERA_AROUND = math.radians(30)  # off the boss's nose towards its right: in front of the antlers, never behind them
CAMERA_ELEVATION = math.radians(30)  # looking down on the weak point


def _ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


class Finisher:
    def __init__(self, game):
        self.game = game
        boss, player = game.boss, game.player
        anim = next(a for a in RIDER["anims"] if a["name"] == RIDER_ANIM)
        self.anim_id, self.events = anim["id"], anim.get("events", [])
        sparks = sorted(e["phase"] for e in self.events if e["type"] == "sparks")
        self.hit_phase, self.shatter_phase = sparks[0], sparks[-1]
        self.land_phase = 255 * LAND_KEY / (anim["keys"] - 1)
        # Where the hand is at the hit, relative to the rider's feet: the feet go there minus this offset.
        self.hand_at_hit = assets.RIGS[RIDER["name"]].attach_position("hand", self.anim_id, self.hit_phase)
        self.boss_anims = {a["name"] for a in boss.rig["anims"]}
        self.phase = 0.0          # rider animation phase, 0..255, as a float
        self.time = 0.0           # s of game time since B
        self.frozen = 0.0         # s of hit stop left
        self.flash = 0.0          # s of hand flash left
        self.after = None         # s of game time since the shatter
        self.dropped = False
        weak, anchor = self.weak_point(), player.anchor(boss)
        dx, dz = weak[0] - anchor[0], weak[2] - anchor[2]
        player.yaw = math.atan2(dx, dz) if math.hypot(dx, dz) > 0.2 else boss.yaw + math.pi
        boss.begin_execution()

    def weak_point(self):
        """World position of the boss's weak point (the `head_weak` attach)."""
        return self.game.boss.attach_position("head_weak")

    def _hand(self):
        return self.game.player.hand()  # the rider plays the finisher (anim_override), feet on the PC point

    def speed(self):
        """Game-time rate: 0 in the hit stop, SLOW from the hit to the shatter, else 1."""
        if self.frozen > 0:
            return 0.0
        return SLOW if self.hit_phase <= self.phase < self.shatter_phase else 1.0

    def update(self, dt):
        """Advance the sequence by dt seconds of real time; True when it has finished."""
        game, boss, player = self.game, self.game.boss, self.game.player
        rate = self.speed()
        self.frozen = max(0.0, self.frozen - dt)
        self.flash = max(0.0, self.flash - dt)
        gdt = dt * rate
        self.time += gdt
        player.orbs.time_scale = rate  # the sparks live in game time too
        boss.update(gdt, player)

        if not self.dropped:
            before = self.phase
            self.phase = min(255.0, self.phase + gdt * 255 / EXECUTE_SECONDS)
            self._place_rider()
            for event in self.events:
                if before < event["phase"] <= self.phase:
                    self._event(event)
            player._advance(gdt, boss)  # sparks and debris
        else:  # falling back into the saddle like after letting go
            player.update(Input(), game.camera, gdt, boss, aim.Aim((0, 0, 0), (0, 0, 1)))

        if self.after is None:
            return False
        self.after += gdt
        boss.fade = _ease((self.after - (DIE - FADE)) / FADE)
        if not self.dropped and self.after >= DIE - FADE:
            self.dropped = True
            player.anim_override = None
            player._hook_button(None, boss)  # let go
        return self.after >= DIE + TAIL and not player.airborne

    def _place_rider(self):
        """The rider's feet: from the hook anchor onto the weak point over keys 0-3, then on it."""
        game, boss, player = self.game, self.game.boss, self.game.player
        hx, hy, hz = self.hand_at_hit  # turned by the rider's heading (Ry)
        c, s = math.cos(player.yaw), math.sin(player.yaw)
        hand = (hx * c + hz * s, hy, -hx * s + hz * c)
        weak = self.weak_point()
        land = (weak[0] - hand[0], weak[1], weak[2] - hand[2])
        k = _ease(self.phase / self.land_phase)
        anchor = player.anchor(boss)
        player.x, player.y, player.z = (a + (b - a) * k for a, b in zip(anchor, land))
        player.anim_override = self.anim_id, int(self.phase)

    def _event(self, event):
        boss = self.game.boss
        kind = event["type"]
        if kind == "cam_shake":
            boss.shake = max(boss.shake, event.get("amp", 0.3))
        elif kind == "sparks":
            self._burst(event.get("n", 8))
            if event["phase"] == self.hit_phase:
                self.game.player.sounds.append(("hit", self._hand()))
                self.frozen, self.flash = HIT_STOP, FLASH_SECONDS
                boss.hit_slot, boss.hit_timer = boss.weak, HIT_STOP + 0.1
            else:  # the weak point shatters
                self.after = 0.0
                boss.finish()
                if BOSS_ANIM in self.boss_anims:
                    boss.play(BOSS_ANIM)
                elif boss.anim != boss.anims["kneel"]:
                    boss.play("kneel")

    def _burst(self, n):
        self.game.player.orbs.burst(n, at=self._hand())

    def objects(self):
        """The hand flash (the sparks are particles, effects.py). Drawn with the `spark` mesh until the renderer
        has `spark_orb` (art.md §6)."""
        out = []
        if self.flash > 0:
            out.append(screen.Obj(mesh_ids.SPARK, *self._hand(), scale=FLASH_SCALE, tint=palette.FLASH))
        return out

    def view(self):
        """In front of the head, a little to its right and above, looking down on the weak point (the antlers
        reach out sideways and back, so they stay out of the shot); it pulls back to the body while the boss dies."""
        boss = self.game.boss
        head = self.weak_point()
        body = boss.bone_position(0)
        k = _ease((self.after or 0.0) / DIE)
        target = tuple(a + (b - a) * k for a, b in zip(head, body))
        heading = boss.yaw - CAMERA_AROUND  # turning right lowers yaw
        dist = CAMERA_DIST[0] + (CAMERA_DIST[1] - CAMERA_DIST[0]) * k
        flat = dist * math.cos(CAMERA_ELEVATION)
        x, z = target[0] + math.sin(heading) * flat, target[2] + math.cos(heading) * flat
        y = max(target[1] + dist * math.sin(CAMERA_ELEVATION), terrain.terrain_height(boss.scene, x, z) + 1.0)
        dx, dy, dz = target[0] - x, target[1] - y, target[2] - z
        return screen.Camera(x, y, z, yaw=math.atan2(dx, dz), pitch=math.atan2(dy, math.hypot(dx, dz)))
