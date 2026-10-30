"""Controller mapping: move stick, button edges and right-stick look rates (docs/plan.md 操作表; on Alia Pad
the right stick replaces tilt; the numbers are in tuning.py)."""

import math
from dataclasses import dataclass

import tuning

# Buttons as the game reads them (main.py makes them from alia-engine's input actions).
BTN_A, BTN_B, BTN_C, BTN_STICK, BTN_START = 1, 2, 4, 8, 16


@dataclass
class RawInput:
    """One step's controller reading, in the units of the console the game was written for (raw stick
    -127..127 with +y up); main.py builds it from alia-engine's actions. The accelerometer and gyro fields
    are the hackathon console's tilt look, unused since the right stick replaced it."""
    seq_ack: int
    connected: int   # bit0 Buttons, bit1 Joystick, bit2 Movement
    held: int        # BTN_* bits held right now
    pressed: int     # BTN_* bits pressed since the previous step
    jx: int
    jy: int
    ax: int          # mg, raw, includes gravity
    ay: int
    az: int
    gx: int          # deg/s / 4 (optional, may be 0)
    gy: int
    render_ms: int
    push_ms: int
    rx: int = 0      # right stick, -127..127, +x right, +y up
    ry: int = 0

STICK_FULL = 120  # raw stick reading treated as full deflection
LOOK_FULL = 127   # right stick full deflection (RawInput rx, ry)


@dataclass
class Input:
    move_x: float = 0.0      # -1..1, positive = right
    move_y: float = 0.0      # -1..1, positive = forward
    yaw_rate: float = 0.0    # rad/s, positive = turn right
    pitch_rate: float = 0.0  # rad/s, positive = look up
    pressed: int = 0         # BTN_* newly pressed since the previous frame
    held: int = 0
    connected: int = 7       # bit0 Buttons, bit1 Joystick, bit2 Movement (always set on Alia Pad)


def look_rate(v, max_rate_deg):
    """Right stick deflection (-1..1) -> view rate in rad/s (tuning.py's dead zone and curve)."""
    t = (abs(v) - tuning.LOOK_DEAD_ZONE) / (1.0 - tuning.LOOK_DEAD_ZONE)
    if t <= 0:
        return 0.0
    return math.copysign(min(t, 1.0) ** tuning.CURVE * math.radians(max_rate_deg), v)


class Controls:
    def update(self, raw):
        """RawInput (or None after a failed frame) -> Input."""
        if raw is None:
            return Input()
        inp = Input(connected=raw.connected)
        buttons = (BTN_A | BTN_B | BTN_C | BTN_START if raw.connected & 1 else 0) | (BTN_STICK if raw.connected & 2 else 0)
        inp.held, inp.pressed = raw.held & buttons, raw.pressed & buttons

        if raw.connected & 2:
            sx = -raw.jx if tuning.STICK_INVERT_X else raw.jx
            sy = -raw.jy if tuning.STICK_INVERT_Y else raw.jy  # positive = down (tuning.STICK_INVERT_Y)
            fx, fy = sx, -sy
            mag = math.hypot(fx, fy)
            if mag > tuning.STICK_DEAD_ZONE:
                scale = min(1.0, (mag - tuning.STICK_DEAD_ZONE) / (STICK_FULL - tuning.STICK_DEAD_ZONE)) / mag
                inp.move_x, inp.move_y = fx * scale, fy * scale
            rx = -raw.rx if tuning.INVERT_YAW else raw.rx
            ry = -raw.ry if tuning.INVERT_PITCH else raw.ry
            inp.yaw_rate = look_rate(rx / LOOK_FULL, tuning.MAX_YAW_RATE_DEG)
            inp.pitch_rate = look_rate(ry / LOOK_FULL, tuning.MAX_PITCH_RATE_DEG)
        return inp


__all__ = ["Controls", "Input", "BTN_A", "BTN_B", "BTN_C", "BTN_START", "BTN_STICK"]
