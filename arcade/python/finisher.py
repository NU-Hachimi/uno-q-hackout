"""The finisher (docs/plan.md): once every part is broken and the weak point is bare, a PC hooked on the
boss's back is told FINISH HIM (B). Pressing B plays this sequence instead of shooting the weak point:
the rider climbs to the head, strikes the weak point three times, it shatters and the boss dies.

Dedicated animations come from the art side (docs/art.md §7): rider `execute` in pc.json and boss `die`
in moose.json, with `strike` events on the rider's impacts and `cam_shake` on the boss's fall. While
they are missing, the sequence uses placeholders (cling / cling_shoot, kneel + fade) on the timings below.
"""

import math

import g3d
import rig
import world
from gen import palette
from player import RIDER

RIDER_ANIM, BOSS_ANIM = "execute", "die"   # used when the rigs have them
CLIMB = 1.2               # s: the rider moves from the hook anchor to the weak point
STRIKES = (1.6, 2.1, 2.6)  # s: impacts (placeholder; the `execute` anim's strike events replace them)
STRIKE_ANIM = 0.45        # s of cling_shoot per placeholder strike
SHATTER = 2.9             # s: the weak point breaks
DIE = 2.5                 # s: the boss's death animation (or kneel placeholder)
FADE = 1.5                # s: the boss sinks into the fog at the end of DIE
TAIL = 0.6                # s held on the empty field before the victory screen
EXECUTE_SECONDS = SHATTER  # s the rider's `execute` animation lasts when it exists
STRIKE_SHAKE, FALL_SHAKE = 0.25, 0.6       # m camera shake
CAMERA_SIDE = (9.0, 19.0)  # m beside the head, pulling back while the boss dies
CAMERA_UP = 2.0           # m above the target


def _ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


class Finisher:
    def __init__(self, game):
        self.game = game
        boss, player = game.boss, game.player
        self.time = 0.0
        self.start = (player.x, player.y, player.z)
        self.rider_anims = {a["name"]: a for a in RIDER["anims"]}
        self.boss_anims = {a["name"]: a for a in boss.rig["anims"]}
        rider = self.rider_anims.get(RIDER_ANIM)
        self.strikes = STRIKES
        if rider:  # the art's strike events set the impact times
            hits = [e["phase"] for e in rider.get("events", []) if e["type"] == "strike"]
            self.strikes = tuple(CLIMB + p / 255 * EXECUTE_SECONDS for p in hits) or STRIKES
        self.struck = 0
        self.shattered = False
        boss.begin_execution()

    def head(self):
        """World position of the boss's weak point (the `head_weak` attach)."""
        boss = self.game.boss
        bones, _ = boss.poses()
        return rig.transform(rig.attach_matrix(boss.rig, bones, "head_weak"), (0, 0, 0))

    def update(self, dt):
        """Advance the sequence; True when it has finished."""
        game, boss, player = self.game, self.game.boss, self.game.player
        self.time += dt
        t = self.time
        boss.update(dt, player)

        # The rider climbs from the anchor to the head and stays there.
        k = _ease(t / CLIMB)
        head = self.head()
        player.x, player.y, player.z = (a + (b - a) * k for a, b in zip(self.start, head))
        player.anim_override = self._rider_anim(t)

        while self.struck < len(self.strikes) and t >= self.strikes[self.struck]:
            self.struck += 1
            boss.hit_slot, boss.hit_timer = boss.weak, 0.1
            player.debris(head, palette.SIGIL)
            game.shake, game.shake_time = STRIKE_SHAKE, 0.25
        if not self.shattered and t >= SHATTER:
            self.shattered = True
            boss.finish()
            game.shake, game.shake_time = FALL_SHAKE, 0.5
            boss.play(BOSS_ANIM if BOSS_ANIM in self.boss_anims else "kneel")
            if BOSS_ANIM not in self.boss_anims:
                boss.anim_time = 0.0
        if self.shattered:
            boss.fade = _ease((t - (SHATTER + DIE - FADE)) / FADE)
        return t >= SHATTER + DIE + TAIL

    def _rider_anim(self, t):
        ids = {name: a["id"] for name, a in self.rider_anims.items()}
        if RIDER_ANIM in ids and t >= CLIMB:
            return ids[RIDER_ANIM], min(255, int(255 * (t - CLIMB) / EXECUTE_SECONDS))
        for hit in self.strikes:
            if 0 <= t - hit < STRIKE_ANIM:
                return ids["cling_shoot"], int(255 * (t - hit) / STRIKE_ANIM)
        return ids["cling"], int(t * 64) & 255

    def view(self):
        """Side-on camera on the head, pulling back and down to the body while the boss dies."""
        boss = self.game.boss
        head = self.head()
        bones, _ = boss.poses()
        body = rig.transform(bones[0], (0, 0, 0))
        k = _ease((self.time - SHATTER) / DIE)
        target = tuple(a + (b - a) * k for a, b in zip(head, body))
        side = (math.cos(boss.yaw), -math.sin(boss.yaw))  # the boss's right, on the ground plane
        dist = CAMERA_SIDE[0] + (CAMERA_SIDE[1] - CAMERA_SIDE[0]) * k
        x, z = target[0] + side[0] * dist, target[2] + side[1] * dist
        y = max(target[1] + CAMERA_UP, world.terrain_height(boss.scene, x, z) + 1.0)
        dx, dy, dz = target[0] - x, target[1] - y, target[2] - z
        return g3d.Camera(x, y, z, yaw=math.atan2(dx, dz), pitch=math.atan2(dy, math.hypot(dx, dz)))

