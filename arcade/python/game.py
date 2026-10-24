"""Round state machine: Ready -> Fight <-> Menu, with Restart and Recalibrate (docs/plan.md)."""

import g3d
from camera import ThirdPersonCamera
from controls import BTN_A, Controls
from player import HP_MAX, Player

READY, FIGHT, MENU, MISSING = "ready", "fight", "menu", "missing"

MSG_MISSING = 8
MSG_MENU = (9, 10, 11)   # Continue, Restart, Recalibrate (api.md §3.5)
MSG_HOLD_AND_PRESS_A = 12
MSG_HINT = 15
HINT_SECONDS = 5.0
MENU_REPEAT = 0.3        # s between menu steps while the stick is held
REQUIRED = 7             # Buttons, Joystick and Movement must all be connected


class Game:
    def __init__(self, scene):
        self.scene = scene
        self.controls = Controls()
        self.restart()

    def restart(self):
        self.player = Player(self.scene)
        self.camera = ThirdPersonCamera(self.player.yaw)
        self.state = READY
        self.menu_item = 0
        self.menu_cooldown = 0.0
        self.hint = 0.0
        self.before_missing = READY
        self.time = 0.0

    def step(self, raw, dt):
        """One frame: RawInput (or None) and elapsed seconds -> (camera, objects, hud, flags)."""
        inp = self.controls.update(raw)
        self.time += dt
        if raw is not None and (raw.connected & REQUIRED) != REQUIRED:
            if self.state != MISSING:
                self.before_missing, self.state = self.state, MISSING
        elif self.state == MISSING and raw is not None:
            # Resume through the menu so play never restarts on its own.
            self.state = MENU if self.before_missing in (FIGHT, MENU) else READY
            self.menu_item = 0

        if self.state == READY:
            self._ready(inp, dt)
        elif self.state == FIGHT:
            self._fight(inp, dt)
        elif self.state == MENU:
            self._menu(inp, dt)
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
        self.camera.turn(inp, dt)
        self.player.update(inp, self.camera, self.camera.view(self.player, self.scene), dt)

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

    def _frame(self):
        view = self.camera.view(self.player, self.scene)
        hud = g3d.Hud(hp=self.player.hp, hp_max=HP_MAX, timer=min(255, int(self.time)))
        if self.state == READY:
            hud.state, hud.msg = g3d.STATE_READY, MSG_HOLD_AND_PRESS_A
        elif self.state == FIGHT:
            hud.state, hud.msg = g3d.STATE_FIGHT, MSG_HINT if self.hint > 0 else 0
        elif self.state == MENU:
            hud.state, hud.msg = g3d.STATE_PAUSED, MSG_MENU[self.menu_item]
        else:
            hud.state, hud.msg = g3d.STATE_PAUSED, MSG_MISSING
        return view, self.player.objects(), hud, 0
