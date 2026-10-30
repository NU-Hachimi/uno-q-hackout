"""Round state machine: Ready -> Intro -> Fight <-> Menu -> Win / Lose, with Restart (docs/plan.md).

Ready: the PC rides back and forth far out, beyond the fog, with the boss hidden and the camera behind it.
A starts the intro: the PC turns and gallops on its own towards the boss, which looms out of the fog, and reins in at the fight spawn; then the
player has control. A during the intro skips to the end of it."""

import math
import random
from dataclasses import dataclass

import aim as aiming
import g3d
import world
from boss import Boss, pick_parts
from camera import ThirdPersonCamera
from controls import BTN_A, BTN_B, BTN_START, Controls, Input
from finisher import Finisher
from player import HP_MAX, Player

GO = BTN_A | BTN_START  # starts a round, skips the intro, restarts after it: either, like a title screen
READY, INTRO, FIGHT, MENU, MISSING, WIN, LOSE, EXECUTE = (
    "ready", "intro", "fight", "menu", "missing", "win", "lose", "execute")

MSG_ARMOR = 2            # objective messages (api.md §3.5)
MSG_HOOK_ON = 3
MSG_CRYSTALS = 17
MSG_JUMP_OFF = 18
MSG_FINISH = 19
MSG_MISSING = 8
MSG_MENU = (9, 10)       # Continue, Restart
MSG_PRESS_A = 1
MSG_VICTORY = 13
MSG_DEFEATED = 14
MSG_HINT = 15
HINT_SECONDS = 5.0
SKY_PERIOD = 0.25        # s between time-of-day updates while the sky is changing
MENU_REPEAT = 0.3        # s between menu steps while the stick is held
REQUIRED = 7             # Buttons, Joystick and Movement must all be connected
SHAKE_SECONDS = 0.35     # camera shake after a stomp or kick lands
SHAKE_HZ = 9.0

READY_SPAWN = (0.0, -108.0)  # (x, z): beyond the fog (fog_far 120 m, art.md §4) from the boss at the centre
READY_TURNS = 40.0           # m; in Ready the PC rides along z = READY_SPAWN between x = -this and +this
READY_THROTTLE = 0.45
FIGHT_SPAWN = (0.0, -30.0)   # where the intro ends and the player takes over
INTRO_BOOST = 1.25           # a little faster than the player's top speed
INTRO_BRAKE = 12.0           # m before the spawn where the horse starts reining in
INTRO_ARRIVE = 0.3           # m; this close to the spawn hands over control
INTRO_REVEAL = 2.0           # s for the boss's extra fade to clear after the intro starts (then only fog)


@dataclass
class Frame:
    """Everything the MCU needs for one frame."""
    camera: g3d.Camera
    objects: list
    hud: g3d.Hud
    rigs: list           # boss, horse, rider (api.md §3.3)
    hook: g3d.Hook
    flags: int = 0

    def pack(self, seq):
        return g3d.pack_frame(seq, self.camera, self.objects, self.hud, rigs=self.rigs, hook=self.hook,
                              flags=self.flags)


class Game:
    def __init__(self, scene, w, seed=None):
        """`w`: the alia_engine.World the round plays in (the boss's rig and colliders, the ground)."""
        self.scene = scene
        self.w = w
        world.set_ground(w, scene)
        self.rng = random.Random(seed)
        self.scene_version = 0  # bumped when the scene (part variants) must be uploaded again
        self.day = 0.0           # s on the day-cycle clock (world.sky_at); runs in Ready and Fight
        self.sky_sent = None     # last g3d_scene_sky payload; None makes the next sky_update() send
        self.sky_wait = 0.0
        self.controls = Controls()
        self.restart()

    def sky_update(self, dt):
        """g3d_scene_sky payload when the sky has changed since the last one sent (at most every SKY_PERIOD)."""
        self.sky_wait -= dt
        if self.sky_wait > 0:
            return None
        payload = g3d.pack_sky(*world.sky_at(self.day))
        if payload == self.sky_sent:
            return None
        self.sky_sent, self.sky_wait = payload, SKY_PERIOD
        return payload

    def restart(self):
        self.scene.slot_variants = pick_parts(self.rng)
        self.scene_version += 1
        if getattr(self, "boss", None):
            self.close()
        self.boss = Boss(self.scene, self.w, random.Random(self.rng.random()))
        self.player = Player(self.scene, self.w, *READY_SPAWN, yaw=math.pi / 2, seed=self.rng.random())  # riding towards +X
        self.ready_to = READY_TURNS
        self.camera = ThirdPersonCamera(self.player.yaw)
        self.boss.fade = 1.0  # out of the scene until the intro
        self.intro_time = 0.0
        self.state = READY
        self.menu_item = 0
        self.menu_cooldown = 0.0
        self.hint = 0.0
        self.before_missing = READY
        self.time = 0.0
        self.aim = None
        self.finisher = None
        self.sounds = []
        self.shake, self.shake_time = 0.0, 0.0

    def step(self, raw, dt):
        """One frame: RawInput (or None) and elapsed seconds -> Frame."""
        inp = self.controls.update(raw)
        self.time += dt
        if raw is not None and (raw.connected & REQUIRED) != REQUIRED:
            if self.state != MISSING:
                self.before_missing, self.state = self.state, MISSING
        elif self.state == MISSING and raw is not None:
            # Resume through the menu so play never restarts on its own.
            self.state = MENU if self.before_missing in (FIGHT, MENU) else self.before_missing
            self.menu_item = 0

        if self.state in (READY, INTRO, FIGHT, EXECUTE):
            self.day += dt
        if self.state == READY:
            self._ready(inp, dt)
        elif self.state == INTRO:
            self._intro(inp, dt)
        elif self.state == FIGHT:
            self._fight(inp, dt)
        elif self.state == MENU:
            self._menu(inp, dt)
        elif self.state == EXECUTE:
            self._execute(dt)
        elif self.state in (WIN, LOSE) and inp.pressed & GO:
            self.restart()
        self.boss.present()
        self.player.present()
        self.sounds = self.boss.sounds + self.player.sounds  # since the last step, for sfx.py
        self.boss.sounds, self.player.sounds = [], []
        return self._frame()

    def close(self):
        """Take the round out of the world."""
        self.boss.close()
        self.player.close()

    def _ready(self, inp, dt):
        self.boss.idle(dt)
        p = self.player
        if (p.x - self.ready_to) * math.copysign(1, self.ready_to) > -5.0:
            self.ready_to = -self.ready_to  # turn back near the end of the line
        self._ride_to(self.ready_to, READY_SPAWN[1], READY_THROTTLE, dt)
        if inp.pressed & GO:
            self.camera = ThirdPersonCamera(self.player.yaw)
            self.player.boost, self.intro_time = INTRO_BOOST, 0.0
            self.state = INTRO

    def _intro(self, inp, dt):
        self.intro_time += dt
        self.boss.idle(dt)
        self.boss.fade = max(0.0, 1.0 - self.intro_time / INTRO_REVEAL)
        p = self.player
        dx, dz = FIGHT_SPAWN[0] - p.x, FIGHT_SPAWN[1] - p.z
        left = math.hypot(dx, dz)
        if inp.pressed & GO or left <= INTRO_ARRIVE:
            self._fight_begins()
            return
        # steer at the spawn while far out, then hold the heading and rein in
        self._ride_to(*FIGHT_SPAWN, min(1.0, math.sqrt(left / INTRO_BRAKE)), dt, steer=left > INTRO_BRAKE)

    def _ride_to(self, x, z, throttle, dt, steer=True):
        """Ride the PC towards (x, z) with a made-up stick (no buttons), the camera behind it."""
        p = self.player
        turn = (math.atan2(x - p.x, z - p.z) - p.yaw + math.pi) % (2 * math.pi) - math.pi if steer else 0.0
        self.camera.turn(Input(), dt)
        # turning right lowers yaw, so a positive turn needs the stick to the left
        p.update(Input(move_x=max(-1.0, min(1.0, -2.0 * turn)), move_y=throttle), self.camera, dt, self.boss, None)
        self.camera.follow(p, dt)

    def _fight_begins(self):
        p = self.player
        p.x, p.z = FIGHT_SPAWN
        p.y = world.terrain_height(self.scene, p.x, p.z)
        p.yaw = math.atan2(self.boss.x - p.x, self.boss.z - p.z)
        p.boost, p.speed, p.standing = 1.0, 0.0, True
        self.boss.fade = 0.0
        self.camera = ThirdPersonCamera(p.yaw)
        self.state = FIGHT
        self.hint = HINT_SECONDS

    def _fight(self, inp, dt):
        if inp.pressed & BTN_START:  # the pause menu, as on any handheld
            self.state, self.menu_item, self.menu_cooldown = MENU, 0, 0.0
            return
        self.hint = max(0.0, self.hint - dt)
        self.shake_time = max(0.0, self.shake_time - dt)
        self.camera.turn(inp, dt, self.player.on_boss)
        self.boss.update(dt, self.player)
        if self.boss.shake:
            self.shake, self.shake_time, self.boss.shake = self.boss.shake, SHAKE_SECONDS, 0.0
        if self.boss.finish_ready(self.player) and (inp.pressed | inp.held) & BTN_B:
            self.finisher, self.state = Finisher(self), EXECUTE  # B finishes instead of shooting
            return
        self.aim = aiming.compute(self.camera.view(self.player, self.scene), self.boss, self.player.hand())
        self.player.update(inp, self.camera, dt, self.boss, self.aim)
        self.camera.follow(self.player, dt)
        for _, pos, tint in self.boss.broken:
            self.player.debris(pos, tint)
        self.boss.broken.clear()
        if self.player.hp <= 0:
            self.state = LOSE

    def _execute(self, dt):
        """The finisher cutscene (finisher.py); no input until the victory screen."""
        self.shake_time = max(0.0, self.shake_time - dt)
        done = self.finisher.update(dt)
        if self.boss.shake:
            self.shake, self.shake_time, self.boss.shake = self.boss.shake, SHAKE_SECONDS, 0.0
        for _, pos, tint in self.boss.broken:
            self.player.debris(pos, tint)
        self.boss.broken.clear()
        if done:
            self.state = WIN

    def objective(self):
        """The message for what to do next (legs, then the back, then the head)."""
        boss, hooked = self.boss, self.player.hooked
        if boss.jump_off_warning(self.player):
            return MSG_JUMP_OFF
        remaining = {s for s in boss.parts if boss.hp[s] > 0}
        if remaining & set(boss.legs):
            return MSG_ARMOR
        if remaining:
            if not hooked:
                return MSG_HOOK_ON
            kinds = boss.remaining_kinds()
            return MSG_ARMOR if any(k.startswith("armor") for k in kinds) else MSG_CRYSTALS
        return MSG_FINISH if boss.finish_ready(self.player) else MSG_HOOK_ON

    def _menu(self, inp, dt):
        self.menu_cooldown = max(0.0, self.menu_cooldown - dt)
        if abs(inp.move_y) < 0.3:
            self.menu_cooldown = 0.0  # stick released: the next push moves at once
        elif self.menu_cooldown == 0.0 and abs(inp.move_y) > 0.5:
            self.menu_item = (self.menu_item + (1 if inp.move_y < 0 else -1)) % len(MSG_MENU)
            self.menu_cooldown = MENU_REPEAT
        if inp.pressed & BTN_START:  # Start again: back to the fight
            self.state = FIGHT
        elif inp.pressed & BTN_A:
            choice = MSG_MENU[self.menu_item]
            if choice == MSG_MENU[1]:
                self.restart()
            else:
                self.state = FIGHT

    def music(self):
        """(track, volume) for audio.Music: the battle theme, softer outside the fight, and the
        victory or defeat jingle at the end of a round (python/music/)."""
        if self.state == WIN:
            return "jingle_victory", 1.0
        if self.state == LOSE:
            return "jingle_defeat", 1.0
        return "bgm_battle", 1.0 if self.state in (INTRO, FIGHT, EXECUTE) else 0.5

    def rigs(self):
        """Rig blocks for this frame: boss, horse, rider (api.md §3.3)."""
        return [self.boss.rig_block()] + self.player.rigs()

    def _frame(self):
        view = self.finisher.view() if self.state == EXECUTE else self.camera.view(self.player, self.scene)
        if self.shake_time > 0:
            fade = self.shake_time / SHAKE_SECONDS
            view.y += self.shake * fade * math.sin(self.time * 2 * math.pi * SHAKE_HZ)
        hud = g3d.Hud(hp=self.player.hp, hp_max=HP_MAX, timer=min(255, int(self.time)),
                      boss_hp=max(1, round(self.boss.health() * 255)) if self.boss.health() > 0 else 0)
        flags = 0
        if self.state == READY:
            hud.state, hud.msg = g3d.STATE_READY, MSG_PRESS_A
        elif self.state == INTRO:
            hud.state, hud.msg = g3d.STATE_FIGHT, 0
            flags |= g3d.FLAG_NO_HUD
        elif self.state == FIGHT:
            msg = self.objective()  # warnings and the finisher prompt beat the opening hint
            hud.state, hud.msg = g3d.STATE_FIGHT, msg if msg in (MSG_JUMP_OFF, MSG_FINISH) or self.hint <= 0 else MSG_HINT
            if self.aim:
                hud.reticle_dx, hud.reticle_dy, hud.reticle_flags = self.aim.dx, self.aim.dy, self.aim.flags
            if self.player.hurt_flash > 0:
                flags |= g3d.FLAG_HURT
        elif self.state == EXECUTE:
            hud.state, flags = g3d.STATE_FIGHT, flags | g3d.FLAG_NO_HUD  # a clean cutscene
        elif self.state == MENU:
            hud.state, hud.msg = g3d.STATE_PAUSED, MSG_MENU[self.menu_item]
        elif self.state == WIN:
            hud.state, hud.msg = g3d.STATE_WIN, MSG_VICTORY
        elif self.state == LOSE:
            hud.state, hud.msg = g3d.STATE_LOSE, MSG_DEFEATED
        else:
            hud.state, hud.msg = g3d.STATE_PAUSED, MSG_MISSING
        objects = self.boss.objects() + self.player.objects()  # rings first: MAX_OBJ cuts the tail
        hook = self.player.hook_block()
        if self.state == EXECUTE:  # the hook is in the rider's hand, not on a rope
            objects, hook = (self.finisher.objects() + self.player.objects())[:g3d.MAX_OBJ], g3d.Hook()
        return Frame(view, objects, hud, self.rigs(), hook, flags)
