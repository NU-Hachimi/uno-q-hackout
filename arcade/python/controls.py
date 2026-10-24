"""Controller mapping: calibrated stick, button edges and tilt-to-look rates (docs/plan.md 操作表)."""

import math
import time
from dataclasses import dataclass

import tilt_config as tilt
from g3d import BTN_A, BTN_B, BTN_C, BTN_STICK
from preview import DEAD_ZONE, INVERT_X, INVERT_Y

STICK_FULL = 120  # raw stick reading treated as full deflection
DEBUG_PERIOD = 0.5  # s between tilt debug lines (tilt_config.DEBUG_LOG)


@dataclass
class Input:
    move_x: float = 0.0      # -1..1, positive = right
    move_y: float = 0.0      # -1..1, positive = forward
    yaw_rate: float = 0.0    # rad/s, positive = turn right
    pitch_rate: float = 0.0  # rad/s, positive = look up
    pressed: int = 0         # BTN_* newly pressed since the previous frame
    held: int = 0
    connected: int = 7       # bit0 Buttons, bit1 Joystick, bit2 Movement


def _norm(v):
    length = math.sqrt(sum(c * c for c in v))
    return tuple(c / length for c in v) if length > 1e-6 else None


def axis_vector(name, invert=False):
    """'x', '-y', ... from tilt_config -> unit vector in Movement sensor axes."""
    text = str(name).strip().lower()
    sign = -1.0 if text.startswith("-") else 1.0
    letter = text.lstrip("+-")
    if letter not in ("x", "y", "z"):
        raise ValueError(f"tilt_config: axis must be x, y or z with an optional '-', got {name!r}")
    v = [0.0, 0.0, 0.0]
    v["xyz".index(letter)] = -sign if invert else sign
    return tuple(v)


def tilt_rate(s, max_rate_deg):
    """Sine of the tilt along an axis -> view rate in rad/s (tilt_config dead zone and curve)."""
    dead = math.sin(math.radians(tilt.DEAD_ZONE_DEG))
    full = math.sin(math.radians(tilt.FULL_DEG))
    t = (abs(s) - dead) / (full - dead)
    if t <= 0:
        return 0.0
    return math.copysign(min(t, 1.0) ** tilt.CURVE * math.radians(max_rate_deg), s)


class Controls:
    def __init__(self):
        self.gravity = None  # smoothed unit gravity vector in sensor axes
        self.neutral = None
        self.yaw_axis = axis_vector(tilt.YAW_AXIS, tilt.INVERT_YAW)
        self.pitch_axis = axis_vector(tilt.PITCH_AXIS, tilt.INVERT_PITCH)
        self.debug_at = 0.0

    def calibrate(self):
        """Take the current pose as neutral (Ready screen A press, or Recalibrate)."""
        self.neutral = self.gravity

    def update(self, raw):
        """RawInput (or None after a failed frame) -> Input."""
        if raw is None:
            return Input()
        inp = Input(connected=raw.connected)
        buttons = (7 if raw.connected & 1 else 0) | (BTN_STICK if raw.connected & 2 else 0)
        inp.held, inp.pressed = raw.held & buttons, raw.pressed & buttons

        if raw.connected & 2:
            sx = -raw.jx if INVERT_X else raw.jx
            sy = -raw.jy if INVERT_Y else raw.jy  # positive = down, as in preview.py
            fx, fy = sx, -sy
            mag = math.hypot(fx, fy)
            if mag > DEAD_ZONE:
                scale = min(1.0, (mag - DEAD_ZONE) / (STICK_FULL - DEAD_ZONE)) / mag
                inp.move_x, inp.move_y = fx * scale, fy * scale

        if raw.connected & 4:
            g = _norm((raw.ax, raw.ay, raw.az))
            if g:
                self.gravity = g if self.gravity is None else _norm(
                    tuple(a + tilt.SMOOTHING * (b - a) for a, b in zip(self.gravity, g)))
                if self.neutral is None:
                    self.neutral = self.gravity
                # For a tilt of angle θ about an axis perpendicular to `axis`, the unit gravity
                # vector moves by about sin θ along `axis`.
                delta = [a - b for a, b in zip(self.gravity, self.neutral)]
                inp.yaw_rate = tilt_rate(sum(d * a for d, a in zip(delta, self.yaw_axis)), tilt.MAX_YAW_RATE_DEG)
                inp.pitch_rate = tilt_rate(sum(d * a for d, a in zip(delta, self.pitch_axis)), tilt.MAX_PITCH_RATE_DEG)
                if tilt.DEBUG_LOG:
                    self._debug(delta, inp)
        return inp

    def _debug(self, delta, inp):
        now = time.monotonic()
        if now - self.debug_at < DEBUG_PERIOD:
            return
        self.debug_at = now
        deg = [math.degrees(math.asin(max(-1.0, min(1.0, d)))) for d in delta]
        print(f"tilt from neutral: x={deg[0]:+4.0f} y={deg[1]:+4.0f} z={deg[2]:+4.0f} deg | "
              f"yaw {math.degrees(inp.yaw_rate):+4.0f} deg/s, pitch {math.degrees(inp.pitch_rate):+4.0f} deg/s",
              flush=True)


__all__ = ["Controls", "Input", "BTN_A", "BTN_B", "BTN_C", "BTN_STICK"]
