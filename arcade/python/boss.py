"""The boss: attack cycle, the parts fitted this round, their health and the phases (docs/plan.md BOSS).

It stands still between attacks. To attack the PC on the ground it turns slowly towards it, then rears
and stomps when the PC is close (a dust ring spreads across the ground and hurts a PC on the ground when it
passes), or kicks or sweeps further out. A PC keeping its distance gets charged: the boss paws the ground
with its head down while still turning, then locks its heading and runs straight through where the PC was;
its chest and forelegs hurt the PC once if they reach it. A PC hooked on for a while gets shaken: JUMP OFF
with C in the window, or be thrown off and hurt.
Breaking both leg parts makes it kneel for a while, then rise; after that every few points of damage
bring it down again. Breaking the legs and the back shatters the head cover and exposes the weak
point, which falls to the finisher (finisher.py).

It is a rig in alia-engine's world (`self.node`): the boss moves and poses it every step, and its
colliders, bones and attach points are read back from the engine (collide.py says what they mean).
"""

import math
import random

import alia_engine as ae
import alia_kit as kit

import assets
import collide
from shown import Shown
import screen
import terrain
from gen import mesh_ids, palette
from gen.rigs import RIGS

RIG_ID = 1
LEG_PARTS = 2                     # leg parts fitted per round, plus the back and the head
ANIM_SECONDS = {"idle": 4.0, "walk": 2.0, "punch_r": 2.4, "sweep": 2.6, "rear_stomp": 2.4, "shake": 4.0,
                "kneel": 2.5, "rise": 2.5, "paw": 1.4, "charge": 0.5}

FAR_ATTACKS = ("punch_r", "sweep")
ATTACK_RANGE = 14.0               # m; it only starts an attack when the PC is this close
STOMP_RANGE = 7.0                 # m; closer than this (by the legs, under the belly) it rears and stomps
CHARGE_RANGE = 35.0               # m; between ATTACK_RANGE and this it charges instead
CHARGE_SPEED = 14.0               # m/s
CHARGE_OVERRUN = 8.0              # m it keeps running past where the PC stood when the charge began
CHARGE_HIT_AHEAD = 4.0            # m ahead of the root: its chest and forelegs, what runs the PC down
CHARGE_HIT_R = 3.5                # m, on the ground plane (the head is far above a mounted PC)
CHARGE_EDGE = 20.0                # m kept from the map edge; the charge stops there
SHAKE_AFTER = 2.5                 # s hooked on before it shakes
THROW_PHASE = 73                  # shake phase of the throw event; JUMP OFF is shown until then
KNEEL_HOLD = 12.0                 # s down on its knees after the kneel animation
KNEEL_DAMAGE = 4                  # damage after rising that brings it down again
ATTACK_INTERVAL = (0.5, 1.5)      # s of standing still between attacks: with the turn, one attack about every 5 s
TURN_RATE = math.radians(25)      # rad/s while turning to attack
FACING = math.radians(10)         # close enough to the PC to strike
MAX_TURN = 1.5                    # s; strikes anyway after turning this long
RECOVER = 0.5                     # s standing still after an attack
FLASH_SECONDS = 0.1               # hit_slot flash (two frames at 20 Hz)
FOOT_CLEARANCE = 0.3              # m added to a shin's radius on the ground
PC_CENTRE = 0.9                   # m above the PC's feet, for hit events
SHOCKWAVE_RADIUS = 14.0           # m; the ring stops here, so standing farther out dodges it
RING_MESH_RADIUS = 1.0            # m, outer radius of shockwave_ring at scale 1
RING_LIFT = 0.2                   # m above the ground under the boss, so terrain bumps don't swallow the ring
HOOK_POINTS = (("root", (0.0, 4.0, 2.4)),   # the top of the shoulder hump, on the back (m in the bone's frame)
               ("head", (0.0, 0.9, 1.15)))  # the brow, just in front of the stone cap
HOOK_RADIUS = 1.0                 # m; aiming this close to a hook point hooks it

STANDING, TURNING, STRIKING, SHAKING, KNEELING, RISING, EXECUTED = (
    "standing", "turning", "striking", "shaking", "kneeling", "rising", "executed")
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


class Boss:
    def __init__(self, scene, w, rng=None):
        """`w`: the alia_engine.World the boss lives in (assets.load() first)."""
        self.scene = scene
        self.w = w
        self.rng = rng or random.Random()
        self.rig = RIGS[scene.rig_id]
        self.anims = anim_ids(self.rig)
        self.variants = list(scene.slot_variants)
        self.x, self.z = 0.0, 0.0
        self.y = terrain.terrain_height(scene, self.x, self.z)
        self.yaw = math.pi  # facing -Z, towards the PC's spawn
        self.anim = self.anims["idle"]
        self.anim_time = 0.0
        self.state = STANDING
        self.timer = self.rng.uniform(*ATTACK_INTERVAL)
        self.attack = None
        self.charge_left = 0.0     # m still to run in the current charge
        self.charge_hit = False
        self.hooked_for = 0.0      # s the PC has been hooked on
        self.knelt = False         # it has knelt once (both legs broken)
        self.damage_since = 0      # damage taken since it last knelt
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
        self.sounds = []   # (name, position) this step, for sfx.py; Game.step clears and collects them
        self.shake = 0.0   # camera shake amplitude (m) from the latest event, read and cleared by the game
        self.waves = []    # spreading shockwaves: [x, y, z, radius, speed, damage]
        self.fade = 0.0    # 0..1 extra blend into the fog (1 = not drawn), for the intro and the finisher
        self._cache = None
        self._spawn()

    def _spawn(self):
        """The rig with this round's parts, and a HOOK sphere at each hook point (a node on its bone)."""
        self.node = node = self.w.spawn_rig(assets.RIGS[self.rig["name"]], position=(self.x, self.y, self.z),
                                            yaw=self.yaw)
        for slot, variant in enumerate(self.variants):
            if variant:
                node.slot_variant(slot, variant)
        names = [b["name"] for b in self.rig["bones"]]
        self.hooks = []
        for name, point in HOOK_POINTS:
            bone = names.index(name)
            hook = self.w.spawn(name="hook_" + name, parent=node.bone(bone), position=point)
            hook.collider = ae.sphere((0, 0, 0), HOOK_RADIUS, layers=collide.HOOK, user=bone)
            self.hooks.append(hook)
        # Every collider node in the rig's order (bones, then slots), so colliders() lists them like the JSON.
        order = [c for i in range(len(names)) for c in node.colliders(i)]
        order += [node.slot(i) for i in range(len(self.rig["slots"]))]
        self.rank = {n: k for k, n in enumerate(order)}
        self.shins = {c for i, n in enumerate(names) if n.startswith("shin") for c in node.colliders(i)}
        self._shown = {"fade": 0.0, "flash": -1}  # what present() last gave the node
        self.shown = Shown(self.w)  # the dust rings (objects())

    def close(self):
        """Take the rig out of the world (a new round spawns a new boss)."""
        if self.node.alive:
            self.node.destroy()
        self.shown.close()

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
        elif self.state in (STANDING, TURNING, PAWING) and self.hooked_for >= SHAKE_AFTER:
            self.state, self.attack = SHAKING, "shake"
            self.play("shake")
        elif self.state == STANDING:
            self.play("idle")
            self.timer -= dt
            if self.timer <= 0 and player.mounted and self._distance(player) <= CHARGE_RANGE:
                self.state, self.timer = TURNING, MAX_TURN
        elif self.state == TURNING:
            self.timer -= dt
            diff = self._turn(player, dt)
            self.play("walk")
            if abs(diff) <= FACING or self.timer <= 0:
                self._choose(player)
        elif self.state == PAWING:
            self._turn(player, dt)  # still tracking: the heading locks when it sets off
            if self.anim_time >= ANIM_SECONDS["paw"]:
                if player.mounted:
                    self.state, self.attack, self.charge_hit = CHARGING, "charge", False
                    self.charge_left = self._distance(player) + CHARGE_OVERRUN
                    self.play("charge")
                else:  # hooked on or falling: nothing to run down
                    self._recover()
        elif self.state == CHARGING:
            self._run(dt, player)
        elif self.state in (STRIKING, SHAKING) and self.anim_time >= ANIM_SECONDS[self.attack]:
            self._recover()
        # Events of whatever animation is playing; a new animation starts its phase from 0.
        self._events(before if self.anim == anim else 0, self.phase(), player)

    def _choose(self, player):
        """Pick the attack by distance: stomp up close, kick or sweep further out, charge from afar."""
        d = self._distance(player)
        if d > ATTACK_RANGE:
            self.state, self.attack = PAWING, "paw"
        else:
            self.state = STRIKING
            self.attack = "rear_stomp" if d <= STOMP_RANGE else self.rng.choice(FAR_ATTACKS)
        self.play(self.attack)

    def _recover(self):
        self.state, self.attack = STANDING, None
        self.timer = RECOVER + self.rng.uniform(*ATTACK_INTERVAL)
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
        diff = kit.angle_between(self.yaw, kit.yaw_to((self.x, self.z), (player.x, player.z)))  # the rig's front is +Z
        step = TURN_RATE * dt
        self.yaw = kit.wrap_angle(self.yaw + kit.clamp(diff, -step, step))
        return diff

    def _run(self, dt, player):
        """Charge straight along the locked heading; running into the PC hurts it once."""
        step = min(CHARGE_SPEED * dt, self.charge_left)
        x, z = self.x + math.sin(self.yaw) * step, self.z + math.cos(self.yaw) * step
        lo, hi = terrain.extent(self.scene, CHARGE_EDGE)
        inside = lo <= x <= hi and lo <= z <= hi
        if inside:
            self.x, self.z = x, z
            self.y = terrain.terrain_height(self.scene, x, z)
            self.charge_left -= step
            self._cache = None
        if not self.charge_hit:
            fx = self.x + math.sin(self.yaw) * CHARGE_HIT_AHEAD
            fz = self.z + math.cos(self.yaw) * CHARGE_HIT_AHEAD
            if math.hypot(player.x - fx, player.z - fz) <= CHARGE_HIT_R:
                self.charge_hit = player.hurt(1) or self.charge_hit
        if self.charge_left <= 0 or not inside:
            self._recover()

    def _events(self, before, now, player):
        """Fire the animation's events whose phase was crossed this frame (api.md §5.1)."""
        anim = self.rig["anims"][self.anim]
        for event in anim.get("events", []):
            if not before < event["phase"] <= now:
                continue
            kind = event["type"]
            if kind == "hit" and player.mounted:
                p = self.bone_position(event["bone_index"])
                if math.dist(p, (player.x, player.y + PC_CENTRE, player.z)) <= event["r"]:
                    player.hurt(event.get("dmg", 1))
            elif kind == "shockwave":
                x, _, z = self.bone_position(event["bone_index"])
                self.waves.append([x, terrain.terrain_height(self.scene, x, z), z, 0.0, event["speed"],
                                   event.get("dmg", 1)])
                self.sounds.append(("stomp", (x, self.waves[-1][1], z)))
            elif kind == "throw" and player.on_boss:
                dx, dz = player.x - self.x, player.z - self.z
                dist = math.hypot(dx, dz) or 1.0
                player.thrown((dx / dist, dz / dist), event.get("dmg", 1))
            elif kind == "cam_shake":
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
        return [screen.Obj(mesh_ids.SHOCKWAVE_RING, x, y + RING_LIFT, z, scale=max(r, 0.1) / RING_MESH_RADIUS, tint=palette.DUST)
                for x, y, z, r, _, _ in self.waves]

    def jump_off_warning(self, player):
        """True while a shake is coming and the PC can still let go safely."""
        return self.state == SHAKING and player.hooked and self.phase() < THROW_PHASE

    # ---- geometry ---------------------------------------------------------------------------
    def _place(self):
        """The rig follows the logic (position, heading, pose) before anything is read from it."""
        node = self.node
        node.position, node.yaw = (self.x, self.y, self.z), self.yaw
        node.animator.anim, node.animator.phase = self.anim, self.phase()
        return node

    def bone_position(self, bone):
        """World position of a bone's origin (name or index), this step."""
        return self._place().bone(bone).world_position

    def attach_position(self, name):
        return self._place().attach_point(name).world_position

    def position_of(self, node):
        """World position of one of the rig's nodes (a hook point, a slot), this step."""
        self._place()
        return node.world_position

    def colliders(self):
        """The BODY and PART colliders this step (collide.Collider, in the rig's order), cached until update()."""
        if self._cache is None:
            self._place()
            mine = [c for c in self.w.colliders(collide.SOLID) if c.node in self.rank]
            mine.sort(key=lambda c: self.rank[c.node])
            self._cache = [collide.Collider.of(c, self.rig) for c in mine]
        return self._cache

    def hook_targets(self):
        """The only places the hook catches, the back and the brow, as spheres around each point
        (the rig's hookable flags are not used)."""
        self._place()
        by_node = {c.node: c for c in self.w.colliders(collide.HOOK)}
        return [collide.Collider.of(by_node[h], self.rig) for h in self.hooks]

    def ray_cast(self, o, d, max_dist, layers=collide.SOLID, exclude_bone=-1):
        """The nearest of the boss's colliders on the unit ray (o, d) within max_dist (collide.Hit), or None.
        `exclude_bone`: nothing on that bone counts (its own shapes and the parts on it)."""
        colliders = self.colliders() + (self.hook_targets() if layers & collide.HOOK else [])
        skip = [c.node for c in colliders if c.bone == exclude_bone]
        hit = self.w.ray_cast(o, d, max_dist, layers, skip)
        c = next((c for c in colliders if hit is not None and c.node == hit.node), None)
        return collide.Hit(hit.distance, hit.point, c) if c is not None else None

    def feet(self):
        """Ground circles (x, z, r) the PC cannot enter: the lower ends of the shins."""
        out = []
        for c in self.colliders():
            if c.node in self.shins:
                foot = min((c.a, c.b), key=lambda p: p[1])
                out.append((foot[0], foot[2], c.r + FOOT_CLEARANCE))
        return out

    def present(self):
        """Once a step, what the rig shows: its fade (1: in the fog, not drawn, still there to hit) and the
        part just hit flashing. Broken parts are out of the world already (_break)."""
        node = self._place()
        self.shown.sync(self.objects())
        if self._shown["fade"] != self.fade:
            node.set_subtree(fade=self.fade)
            self._shown["fade"] = self.fade
        flash = self.hit_slot if self.hit_timer > 0 else -1
        if self._shown["flash"] != flash:
            for slot, tint, fog in ((self._shown["flash"], 0, True), (flash, palette.FLASH, False)):
                if slot >= 0:
                    part = node.slot(slot)
                    part.tint, part.ground_fog = tint, fog
            self._shown["flash"] = flash

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
        part = self.node.slot(slot)
        part.active = False  # out of the world: not drawn, its collider off
        self._cache = None
        mesh = self.rig["slots"][slot]["variants"][self.variants[slot]] or ""
        self.broken.append((slot, self.position_of(part), part_tint(mesh)))
        self.sounds.append(("break", self.broken[-1][1]))

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
        return screen.Rig(rig_id=RIG_ID, anim=self.anim, phase=self.phase(),
                       hit_slot=self.hit_slot if self.hit_timer > 0 else 0xFF,
                       x=self.x, y=self.y, z=self.z, yaw=self.yaw, part_alive=self.alive, fade=self.fade)
