"""The boss: attack cycle, the parts fitted this round, their health and the phases (docs/plan.md BOSS).

It stands still between attacks. To attack it turns slowly towards the PC, then kicks, sweeps or rears up and
stomps; the stomp sends a dust ring across the ground that hurts the PC if it is on the ground when the ring passes.
A PC keeping its distance gets charged: the boss paws the ground with its head down while still turning, then locks
its heading and runs straight through where the PC was; its chest and forelegs hurt the PC once if they reach it.
Breaking both leg parts makes it kneel for good (no more attacks); breaking the legs and the back
shatters the head cover and exposes the weak point, which can only be hurt while hooked on.
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
ANIM_SECONDS = {"idle": 4.0, "walk": 2.0, "kneel": 2.5, "punch_r": 2.4, "sweep": 2.6, "rear_stomp": 2.4, "paw": 1.4,
                "charge": 0.5}

ATTACKS = ("punch_r", "sweep", "rear_stomp")
ATTACK_RANGE = 14.0               # m; it only starts an attack when the PC is this close
CHARGE_RANGE = 35.0               # m; between ATTACK_RANGE and this it charges instead
CHARGE_SPEED = 14.0               # m/s
CHARGE_OVERRUN = 8.0              # m it keeps running past where the PC stood when the charge began
CHARGE_HIT_AHEAD = 4.0            # m ahead of the root: its chest and forelegs, what runs the PC down
CHARGE_HIT_R = 3.5                # m, on the ground plane (the head is far above a mounted PC)
CHARGE_EDGE = 20.0                # m kept from the map edge; the charge stops there
ATTACK_INTERVAL = (5.0, 8.0)      # s of standing still between attacks
TURN_RATE = math.radians(25)      # rad/s while turning to attack
FACING = math.radians(10)         # close enough to the PC to strike
MAX_TURN = 3.0                    # s; strikes anyway after turning this long
RECOVER = 1.0                     # s standing still after an attack
FLASH_SECONDS = 0.1               # hit_slot flash (two frames at 20 Hz)
FOOT_CLEARANCE = 0.3              # m added to a shin's radius on the ground
PC_CENTRE = 0.9                   # m above the PC's feet, for hit events
SHOCKWAVE_RADIUS = 14.0           # m; the ring stops here, so standing farther out dodges it
RING_MESH_RADIUS = 1.0            # m, outer radius of shockwave_ring at scale 1
RING_LIFT = 0.2                   # m above the ground under the boss, so terrain bumps don't swallow the ring

STANDING, TURNING, STRIKING, KNEELING = "standing", "turning", "striking", "kneeling"
PAWING, CHARGING = "pawing", "charging"


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
        self.charge_left = 0.0  # m still to run in the current charge
        self.charge_hit = False
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
        self.waves = []    # spreading shockwaves: [x, y, z, radius, speed, damage]
        self.fade = 0.0    # 0..1 extra blend into the fog (1 = not drawn), for the intro
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
        before = self.phase()
        self.anim_time += dt
        self.hit_timer = max(0.0, self.hit_timer - dt)
        self._cache = None
        self._spread(dt, player)
        if self.state == KNEELING:
            return
        self.timer -= dt
        if self.state == STANDING:
            self.play("idle")
            if self.timer <= 0 and self._distance(player) <= CHARGE_RANGE:
                self.state, self.timer = TURNING, MAX_TURN
        if self.state == TURNING:
            diff = self._turn(player, dt)
            self.play("walk")
            if abs(diff) <= FACING or self.timer <= 0:
                if self._distance(player) > ATTACK_RANGE:
                    self.state, self.attack = PAWING, "paw"
                else:
                    self.state, self.attack = STRIKING, self.rng.choice(ATTACKS)
                self.play(self.attack)
                before = 0
        if self.state == PAWING:
            self._turn(player, dt)  # still tracking: the heading locks when it sets off
            self._events(before, self.phase(), player)
            if self.anim_time >= ANIM_SECONDS["paw"]:
                self.state, self.attack, self.charge_hit = CHARGING, "charge", False
                self.charge_left = self._distance(player) + CHARGE_OVERRUN
                self.play("charge")
        if self.state == CHARGING:
            self._run(dt, player)
            return
        if self.state == STRIKING:
            self._events(before, self.phase(), player)
            if self.anim_time >= ANIM_SECONDS[self.attack]:
                self.state, self.timer, self.attack = STANDING, RECOVER + self.rng.uniform(*ATTACK_INTERVAL), None
                self.play("idle")

    def idle(self, dt):
        """Breathe in place without attacking (Ready and the intro)."""
        self.play("idle")
        self.anim_time += dt
        self._cache = None

    def _distance(self, player):
        return math.hypot(player.x - self.x, player.z - self.z)

    def _turn(self, player, dt):
        """Turn towards the PC at TURN_RATE; returns the angle still to go."""
        diff = _wrap(math.atan2(player.x - self.x, player.z - self.z) - self.yaw)  # the rig's front is +Z
        step = TURN_RATE * dt
        self.yaw = _wrap(self.yaw + max(-step, min(step, diff)))
        return diff

    def _run(self, dt, player):
        """Charge straight along the locked heading; running into the PC hurts it once."""
        step = min(CHARGE_SPEED * dt, self.charge_left)
        x, z = self.x + math.sin(self.yaw) * step, self.z + math.cos(self.yaw) * step
        lo, hi = world.extent(self.scene, CHARGE_EDGE)
        inside = lo <= x <= hi and lo <= z <= hi
        if inside:
            self.x, self.z = x, z
            self.y = world.terrain_height(self.scene, x, z)
            self.charge_left -= step
            self._cache = None
        if not self.charge_hit:
            fx = self.x + math.sin(self.yaw) * CHARGE_HIT_AHEAD
            fz = self.z + math.cos(self.yaw) * CHARGE_HIT_AHEAD
            if math.hypot(player.x - fx, player.z - fz) <= CHARGE_HIT_R:
                self.charge_hit = player.hurt(1) or self.charge_hit
        if self.charge_left <= 0 or not inside:
            self.state, self.timer, self.attack = STANDING, RECOVER + self.rng.uniform(*ATTACK_INTERVAL), None
            self.play("idle")

    def _events(self, before, now, player):
        """Fire the animation's events whose phase was crossed this frame (api.md §5.1)."""
        anim = self.rig["anims"][self.anim]
        for event in anim.get("events", []):
            if not before < event["phase"] <= now:
                continue
            if event["type"] == "hit":
                bones, _ = self.poses()
                p = rig.transform(bones[event["bone_index"]], (0, 0, 0))
                if math.dist(p, (player.x, player.y + PC_CENTRE, player.z)) <= event["r"]:
                    player.hurt(event.get("dmg", 1))
            elif event["type"] == "shockwave":
                bones, _ = self.poses()
                x, _, z = rig.transform(bones[event["bone_index"]], (0, 0, 0))
                self.waves.append([x, world.terrain_height(self.scene, x, z), z, 0.0, event["speed"],
                                   event.get("dmg", 1)])
            elif event["type"] == "cam_shake":
                self.shake = max(self.shake, event.get("amp", 0.3))

    def _spread(self, dt, player):
        """Grow each ring; it hurts the PC once, when it sweeps past the PC's feet on the ground."""
        for wave in self.waves:
            x, _, z, before, speed, damage = wave
            wave[3] = min(SHOCKWAVE_RADIUS, before + speed * dt)
            if player.mounted and before < math.hypot(player.x - x, player.z - z) <= wave[3]:
                player.hurt(damage)
        self.waves = [w for w in self.waves if w[3] < SHOCKWAVE_RADIUS]

    def objects(self):
        """The dust rings on the ground (art.md §6)."""
        return [g3d.Obj(mesh_ids.SHOCKWAVE_RING, x, y + RING_LIFT, z, scale=max(r, 0.1) / RING_MESH_RADIUS, tint=palette.DUST)
                for x, y, z, r, _, _ in self.waves]

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
        if slot == self.weak:
            return self.weak_exposed() and hooked
        return True

    def damage(self, slot, amount, hooked=False):
        """Apply a hit; returns True when it broke the part."""
        if not self.damageable(slot, hooked):
            return False
        self.hp[slot] = max(0, self.hp[slot] - amount)
        self.hit_slot, self.hit_timer = slot, FLASH_SECONDS
        if self.hp[slot] > 0:
            return False
        self._break(slot)
        if self.state != KNEELING and all(self.hp[s] == 0 for s in self.legs):
            self.state, self.attack = KNEELING, None
            self.play("kneel")
        if all(self.hp[s] == 0 for s in self.parts) and self.alive & (1 << self.cover):
            self._break(self.cover)  # the stone cap shatters and the weak point shows
        return True

    def _break(self, slot):
        self.alive &= ~(1 << slot)
        _, slots = self.poses()
        mesh = self.rig["slots"][slot]["variants"][self.variants[slot]] or ""
        self.broken.append((slot, rig.transform(slots[slot], (0, 0, 0)), part_tint(mesh)))

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
