"""The boss: attack cycle, the parts fitted this round, their health and the phases (docs/plan.md BOSS).

It stands still between attacks. To attack the PC on the ground it turns slowly towards it, then rears
and stomps (shockwave) when the PC is close, or kicks or sweeps further out. A PC hooked on for a while
gets shaken: JUMP OFF with C in the window, or be thrown off and hurt.
Breaking both leg parts makes it kneel for a while, then rise; after that every few points of damage
bring it down again. Breaking the legs and the back shatters the head cover and exposes the weak
point, which can only be hurt while hooked on.
"""

import math
import random

import collide
import g3d
import rig
import world
from gen import mesh_ids, palette
from gen.rigs import RIGS

RIG_ID = 1
LEG_PARTS = 2                     # leg parts fitted per round, plus the back and the head
ANIM_SECONDS = {"idle": 4.0, "walk": 2.0, "punch_r": 2.4, "sweep": 2.6, "rear_stomp": 3.0, "shake": 4.0,
                "kneel": 2.5, "rise": 2.5}

FAR_ATTACKS = ("punch_r", "sweep")
ATTACK_RANGE = 14.0               # m; it only starts an attack when the PC is this close
STOMP_RANGE = 7.0                 # m; closer than this (by the legs, under the belly) it rears and stomps
SHOCKWAVE_MAX = 14.0              # m; the dust ring stops spreading here
SHAKE_AFTER = 2.5                 # s hooked on before it shakes
THROW_PHASE = 73                  # shake phase of the throw event; JUMP OFF is shown until then
KNEEL_HOLD = 12.0                 # s down on its knees after the kneel animation
KNEEL_DAMAGE = 4                  # damage after rising that brings it down again
ATTACK_INTERVAL = (5.0, 8.0)      # s of standing still between attacks
TURN_RATE = math.radians(25)      # rad/s while turning to attack
FACING = math.radians(10)         # close enough to the PC to strike
MAX_TURN = 3.0                    # s; strikes anyway after turning this long
RECOVER = 1.0                     # s standing still after an attack
FLASH_SECONDS = 0.1               # hit_slot flash (two frames at 20 Hz)
FOOT_CLEARANCE = 0.3              # m added to a shin's radius on the ground
PC_CENTRE = 0.9                   # m above the PC's feet, for hit events

STANDING, TURNING, STRIKING, SHAKING, KNEELING, RISING, EXECUTED = (
    "standing", "turning", "striking", "shaking", "kneeling", "rising", "executed")


def anim_ids(rig_data):
    return {a["name"]: a["id"] for a in rig_data["anims"]}


def slots_tagged(rig_data, *tags):
    return [i for i, s in enumerate(rig_data["slots"]) if any(t in s.get("tags", []) for t in tags)]


def pick_parts(rng, rig_data=RIGS[RIG_ID]):
    """Slot variants for one round: two random leg slots and the back, each with a random variant,
    the head cover and weak point always; every other slot is empty (variant 0)."""
    variants = [0] * len(rig_data["slots"])
    for slot in rng.sample(slots_tagged(rig_data, "leg"), LEG_PARTS) + slots_tagged(rig_data, "back"):
        variants[slot] = rng.randint(1, len(rig_data["slots"][slot]["variants"]) - 1)
    for slot in slots_tagged(rig_data, "cover", "weak"):
        variants[slot] = 1
    return variants


def part_tint(mesh_name):
    """Palette colour for a part's debris (art.md §6)."""
    if mesh_name.startswith("head_cap"):
        return palette.STONE_LIGHT
    if mesh_name.startswith(("crystal", "sigil")):
        return palette.SIGIL
    return palette.STONE_MID


def _wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


class Boss:
    def __init__(self, scene, rng=None):
        self.scene = scene
        self.rng = rng or random.Random()
        self.rig = RIGS[scene.rig_id]
        self.anims = anim_ids(self.rig)
        self.variants = list(scene.slot_variants)
        self.x, self.z = 0.0, 0.0
        self.y = world.terrain_height(scene, self.x, self.z)
        self.yaw = math.pi  # facing -Z, towards the PC's spawn
        self.anim = self.anims["idle"]
        self.anim_time = 0.0
        self.state = STANDING
        self.timer = self.rng.uniform(*ATTACK_INTERVAL)
        self.attack = None
        self.hooked_for = 0.0      # s the PC has been hooked on
        self.knelt = False         # it has knelt once (both legs broken)
        self.damage_since = 0      # damage taken since it last rose
        self.waves = []            # shockwaves: [x, z, radius, damage, speed]
        self.fade = 0.0            # 0..1 sinking into the fog after the finisher
        slots = self.rig["slots"]
        self.legs = [i for i in slots_tagged(self.rig, "leg") if self.variants[i]]
        self.parts = [i for i in slots_tagged(self.rig, "phase1", "phase2") if self.variants[i]]
        self.cover = slots_tagged(self.rig, "cover")[0]
        self.weak = slots_tagged(self.rig, "weak")[0]
        self.hp = {i: slots[i].get("hp", 0) for i in self.parts + [self.weak]}
        self.hp_total = sum(self.hp.values()) or 1
        self.alive = sum(1 << i for i, v in enumerate(self.variants) if v)
        self.hit_slot, self.hit_timer = 0xFF, 0.0
        self.broken = []   # (slot, world position, tint) broken since the game last read it, for debris
        self.shake = 0.0   # camera shake amplitude (m) from the latest event, read and cleared by the game
        self._cache = None

    # ---- animation -----------------------------------------------------------------------
    def play(self, name):
        if self.anim != self.anims[name]:
            self.anim, self.anim_time = self.anims[name], 0.0

    def phase(self, time=None):
        anim = self.rig["anims"][self.anim]
        t = (self.anim_time if time is None else time) / ANIM_SECONDS.get(anim["name"], 2.0)
        return int(t * 256) % 256 if anim["loop"] else min(255, int(t * 255))

    # ---- behaviour ------------------------------------------------------------------------
    def update(self, dt, player):
        anim, before = self.anim, self.phase()
        self.anim_time += dt
        self.hit_timer = max(0.0, self.hit_timer - dt)
        self._cache = None
        self._spread(dt, player)
        self.hooked_for = self.hooked_for + dt if player.hooked else 0.0
        if self.state == EXECUTED:  # finisher.py drives the animation; only its events still fire
            pass
        elif self.state == KNEELING:
            if self.anim_time >= ANIM_SECONDS["kneel"] + KNEEL_HOLD:
                self.state = RISING
                self.play("rise")
        elif self.state == RISING:
            if self.anim_time >= ANIM_SECONDS["rise"]:
                self._recover()
        elif self.state == STANDING:
            self.play("idle")
            self.timer -= dt
            if self.hooked_for >= SHAKE_AFTER:
                self.state, self.attack = SHAKING, "shake"
                self.play("shake")
            elif self.timer <= 0 and player.mounted and self._distance(player) <= ATTACK_RANGE:
                self.state, self.timer = TURNING, MAX_TURN
        elif self.state == TURNING:
            self.timer -= dt
            diff = _wrap(math.atan2(player.x - self.x, player.z - self.z) - self.yaw)  # the rig's front is +Z
            step = TURN_RATE * dt
            self.yaw = _wrap(self.yaw + max(-step, min(step, diff)))
            self.play("walk")
            if abs(diff) <= FACING or self.timer <= 0:
                close = self._distance(player) <= STOMP_RANGE
                self.state, self.attack = STRIKING, "rear_stomp" if close else self.rng.choice(FAR_ATTACKS)
                self.play(self.attack)
        elif self.state in (STRIKING, SHAKING) and self.anim_time >= ANIM_SECONDS[self.attack]:
            self._recover()
        # Events of whatever animation is playing; a new animation starts its phase from 0.
        self._events(before if self.anim == anim else 0, self.phase(), player)

    def _recover(self):
        self.state, self.attack = STANDING, None
        self.timer = RECOVER + self.rng.uniform(*ATTACK_INTERVAL)
        self.damage_since = 0
        self.play("idle")

    def _distance(self, player):
        return math.hypot(player.x - self.x, player.z - self.z)

    def _events(self, before, now, player):
        """Fire the animation's events whose phase was crossed this frame (api.md §5.1)."""
        anim = self.rig["anims"][self.anim]
        for event in anim.get("events", []):
            if not before < event["phase"] <= now:
                continue
            kind = event["type"]
            if kind == "hit" and player.mounted:
                bones, _ = self.poses()
                p = rig.transform(bones[event["bone_index"]], (0, 0, 0))
                if math.dist(p, (player.x, player.y + PC_CENTRE, player.z)) <= event["r"]:
                    player.hurt(event.get("dmg", 1))
            elif kind == "shockwave":
                bones, _ = self.poses()
                p = rig.transform(bones[event.get("bone_index", 0)], (0, 0, 0))  # under the root
                self.waves.append([p[0], p[2], 0.0, event.get("dmg", 1), event.get("speed", 12.0)])
            elif kind == "throw" and player.hook in ("pulling", "hooked"):
                dx, dz = player.x - self.x, player.z - self.z
                dist = math.hypot(dx, dz) or 1.0
                player.thrown((dx / dist, dz / dist), event.get("dmg", 1))
            elif kind == "cam_shake":
                self.shake = max(self.shake, event.get("amp", 0.3))

    def _spread(self, dt, player):
        """Grow the shockwaves; a ring front passing a PC riding on the ground hurts it."""
        alive = []
        for wave in self.waves:
            x, z, r, damage, speed = wave
            grown = min(SHOCKWAVE_MAX, r + speed * dt)
            d = math.hypot(player.x - x, player.z - z)
            if player.mounted and r < d <= grown:
                player.hurt(damage)
            wave[2] = grown
            if grown < SHOCKWAVE_MAX:
                alive.append(wave)
        self.waves = alive

    def shockwave_objects(self):
        """Dust rings, scaled to their radius and sunk so that at most ~1.2 m shows above the ground."""
        out = []
        for x, z, r, _, _ in self.waves:
            radius = max(r, 0.5)
            y = world.terrain_height(self.scene, x, z) - max(0.0, 0.35 * radius - 1.2)
            out.append(g3d.Obj(mesh_ids.SHOCKWAVE_RING, x, y, z, scale=radius))
        return out

    def jump_off_warning(self, player):
        """True while a shake is coming and the PC can still let go safely."""
        return self.state == SHAKING and player.hooked and self.phase() < THROW_PHASE

    # ---- geometry ---------------------------------------------------------------------------
    def poses(self):
        """(bone world transforms, slot world transforms) this frame, cached until update()."""
        if self._cache is None:
            bones = rig.world_poses(self.rig, self.anim, self.phase(), self.x, self.y, self.z, self.yaw)
            slots = [rig.slot_matrix(self.rig, bones, i) for i in range(len(self.rig["slots"]))]
            self._cache = bones, slots
        return self._cache

    def colliders(self):
        bones, slots = self.poses()
        return collide.boss_colliders(self.rig, bones, slots, self.alive, self.variants)

    def feet(self):
        """Ground circles (x, z, r) the PC cannot enter: the lower ends of the shins."""
        bones, _ = self.poses()
        out = []
        for index, bone in enumerate(self.rig["bones"]):
            if not bone["name"].startswith("shin"):
                continue
            for c in bone.get("colliders", []):
                ends = [rig.transform(bones[index], c["a"]), rig.transform(bones[index], c["b"])]
                foot = min(ends, key=lambda p: p[1])
                out.append((foot[0], foot[2], c["r"] + FOOT_CLEARANCE))
        return out

    # ---- damage -------------------------------------------------------------------------------
    def damageable(self, slot, hooked=False):
        if not self.alive & (1 << slot) or slot not in self.hp:
            return False
        return slot != self.weak  # the weak point falls to the finisher, not to shots

    def damage(self, slot, amount, hooked=False):
        """Apply a hit; returns True when it broke the part."""
        if not self.damageable(slot, hooked):
            return False
        dealt = min(self.hp[slot], amount)
        self.hp[slot] -= dealt
        self.hit_slot, self.hit_timer = slot, FLASH_SECONDS
        broke = self.hp[slot] == 0
        if broke:
            self._break(slot)
            if all(self.hp[s] == 0 for s in self.parts) and self.alive & (1 << self.cover):
                self._break(self.cover)  # the stone cap shatters and the weak point shows
        if self.state not in (KNEELING, RISING):
            if not self.knelt and all(self.hp[s] == 0 for s in self.legs):
                self.knelt = True
                self._kneel()
            elif self.knelt:
                self.damage_since += dealt
                if self.damage_since >= KNEEL_DAMAGE:
                    self._kneel()
        return broke

    def _kneel(self):
        self.state, self.attack, self.damage_since = KNEELING, None, 0
        self.play("kneel")

    def _break(self, slot):
        self.alive &= ~(1 << slot)
        _, slots = self.poses()
        mesh = self.rig["slots"][slot]["variants"][self.variants[slot]] or ""
        self.broken.append((slot, rig.transform(slots[slot], (0, 0, 0)), part_tint(mesh)))

    def begin_execution(self):
        """The finisher starts: stop attacking and drop pending shockwaves."""
        self.state, self.attack, self.waves = EXECUTED, None, []

    def finish(self):
        """The finisher breaks the weak point."""
        if self.hp.get(self.weak):
            self.hp[self.weak] = 0
            self._break(self.weak)

    def finish_ready(self, player):
        """FINISH HIM: every part is gone, the weak point is bare and the PC is hooked on."""
        return (self.weak_exposed() and self.hp.get(self.weak, 0) > 0 and player.hooked
                and self.state not in (SHAKING, EXECUTED))

    def weak_exposed(self):
        return not self.alive & (1 << self.cover)

    def defeated(self):
        return self.hp.get(self.weak, 0) == 0

    def remaining_kinds(self):
        """Mesh names of the parts still to break, for the objective message."""
        return [self.rig["slots"][s]["variants"][self.variants[s]] for s in self.parts if self.hp[s] > 0]

    def health(self):
        """0..1 of the remaining health of this round's parts and weak point, for the HUD bar."""
        return sum(self.hp.values()) / self.hp_total

    def rig_block(self):
        return g3d.Rig(rig_id=RIG_ID, anim=self.anim, phase=self.phase(),
                       hit_slot=self.hit_slot if self.hit_timer > 0 else 0xFF,
                       x=self.x, y=self.y, z=self.z, yaw=self.yaw, part_alive=self.alive, fade=self.fade)
