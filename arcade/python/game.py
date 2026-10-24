"""Round state machine: Ready -> Fight <-> Menu -> Win / Lose, with Restart and Recalibrate (docs/plan.md)."""

import math
import random
from dataclasses import dataclass

import aim as aiming
import g3d
import world
from boss import Boss, pick_parts
from camera import ThirdPersonCamera
from controls import BTN_A, BTN_B, Controls
from finisher import Finisher
from player import HP_MAX, Player

READY, FIGHT, MENU, MISSING, WIN, LOSE, EXECUTE = "ready", "fight", "menu", "missing", "win", "lose", "execute"

MSG_ARMOR = 2            # objective messages (api.md §3.5)
MSG_HOOK_ON = 3
MSG_CRYSTALS = 17
MSG_JUMP_OFF = 18
MSG_FINISH = 19
MSG_MISSING = 8
MSG_MENU = (9, 10, 11)   # Continue, Restart, Recalibrate
MSG_HOLD_AND_PRESS_A = 12
MSG_VICTORY = 13
MSG_DEFEATED = 14
MSG_HINT = 15
HINT_SECONDS = 5.0
SKY_PERIOD = 0.25        # s between time-of-day updates while the sky is changing
MENU_REPEAT = 0.3        # s between menu steps while the stick is held
REQUIRED = 7             # Buttons, Joystick and Movement must all be connected
SHAKE_SECONDS = 0.35     # camera shake after a stomp or kick lands
SHAKE_HZ = 9.0


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
    def __init__(self, scene, seed=None):
        self.scene = scene
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
        self.boss = Boss(self.scene, random.Random(self.rng.random()))
        self.player = Player(self.scene, seed=self.rng.random())
        self.camera = ThirdPersonCamera(self.player.yaw)
        self.state = READY
        self.menu_item = 0
        self.menu_cooldown = 0.0
        self.hint = 0.0
        self.before_missing = READY
        self.time = 0.0
        self.aim = None
        self.finisher = None
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

        if self.state in (READY, FIGHT):
            self.day += dt
        if self.state == READY:
            self._ready(inp, dt)
        elif self.state == FIGHT:
            self._fight(inp, dt)
        elif self.state == MENU:
            self._menu(inp, dt)
        elif self.state == EXECUTE:
            self._execute(dt)
        elif self.state in (WIN, LOSE) and inp.pressed & BTN_A:
            self.restart()
        return self._frame()

    def _ready(self, inp, dt):
        self.camera.yaw += 0.15 * dt  # slow drift around the PC while waiting
        if inp.pressed & BTN_A:
            self.controls.calibrate()
            self.camera = ThirdPersonCamera(self.player.yaw)
            self.state = FIGHT
            self.hint = HINT_SECONDS

    def _fight(self, inp, dt):
        if inp.pressed & BTN_A:
            self.state, self.menu_item, self.menu_cooldown = MENU, 0, 0.0
            return
        self.hint = max(0.0, self.hint - dt)
        self.shake_time = max(0.0, self.shake_time - dt)
        self.camera.turn(inp, dt)
        self.boss.update(dt, self.player)
        if self.boss.shake:
            self.shake, self.shake_time, self.boss.shake = self.boss.shake, SHAKE_SECONDS, 0.0
        if self.boss.finish_ready(self.player) and (inp.pressed | inp.held) & BTN_B:
            self.finisher, self.state = Finisher(self), EXECUTE  # B finishes instead of shooting
            return
        colliders = self.boss.colliders()
        self.aim = aiming.compute(self.camera.view(self.player, self.scene), colliders, self.player.hand())
        self.player.update(inp, self.camera, dt, self.boss, self.aim, colliders)
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
        self.player._advance(dt, self.boss)  # debris and sparks keep moving
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
        if inp.pressed & BTN_A:
            choice = MSG_MENU[self.menu_item]
            if choice == MSG_MENU[1]:
                self.restart()
            else:
                if choice == MSG_MENU[2]:
                    self.controls.calibrate()
                self.state = FIGHT

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
            hud.state, hud.msg = g3d.STATE_READY, MSG_HOLD_AND_PRESS_A
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
        return Frame(view, objects, hud, self.rigs(), self.player.hook_block(), flags)
