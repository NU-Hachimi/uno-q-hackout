"""Megalith's look on alia-engine (art.md §4): the Look grading applied to the palette and the sky, the
banded distance fog, the ground fog, the sun and the character light, and the hurt overlay. The numbers are
the hackathon renderer's (its sketch/render.cpp), at 640x360 instead of 240x160."""

import math
import struct

from gen import palette as pal

_LOOK = struct.Struct("<32HBBBbBHHBBB")

SUN_AMBIENT, SUN_DIFFUSE, CHAR_AMBIENT, CHAR_DIFFUSE = 0.5, 0.65, 0.55, 0.6
NEAR_PLANE = 0.5
FOG_STEPS = 16
FOG_FULL = 0.92            # fully fogged at this fraction of the way from fog_near to fog_far
GROUND_FOG_TOP, GROUND_FOG_RAMP = 9.0, 30.0
SKY_SPAN = 0.55            # rad above the horizon where the sky reaches sky_top
HURT_ALPHA = 0x40          # 8/32, as the MCU's blend


def rgb888(c565):
    r, g, b = (c565 >> 11) & 31, (c565 >> 5) & 63, c565 & 31
    return ((r << 3 | r >> 2) << 16) | ((g << 2 | g >> 4) << 8) | (b << 3 | b >> 2)


def rgba(c565, alpha=0xFF):
    return (rgb888(c565) << 8) | alpha


def grade(c, look):
    """Mode 1 grading (art.md §4, sketch/scene.cpp grade()): RGB565 in, RGB565 out."""
    mode, sat, con, bri, gam, lift, gain = look
    if mode == 0:
        return c

    def split(v):
        return ((v >> 11) & 31) / 31.0, ((v >> 5) & 63) / 63.0, (v & 31) / 31.0

    rgb, lo, hi = split(c), split(lift), split(gain)
    y = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    exponent = 64.0 / (gam or 64)
    out = []
    for i in range(3):
        v = y + (rgb[i] - y) * sat / 128.0
        v = min(1.0, max(0.0, (v - 0.5) * con / 128.0 + 0.5 + bri / 128.0))
        out.append(min(1.0, max(0.0, lo[i] + v ** exponent * (hi[i] - lo[i]))))
    return (round(out[0] * 31) << 11) | (round(out[1] * 63) << 5) | round(out[2] * 31)


class Look:
    """The engine's palette, sky, fog and lights, following the time of day and the camera."""

    def __init__(self, engine):
        self.e = engine
        self.palette = list(pal.PALETTE_565)  # graded by the current Look
        self.light = (0.0, -1.0, 0.0)         # the direction sunlight travels

    def set_sky(self, fields, look_block):
        """world.sky_at() output: scene colours (RGB565), fog in 2 m units, sun in BAM8, and the Look. Returns
        the two grass tones, graded (the terrain is baked with them)."""
        look = _LOOK.unpack(look_block)
        params = look[32:39]
        self.palette = [grade(c, params) for c in look[:32]]
        self.e.set_palette(b"".join(rgb888(c).to_bytes(3, "big") for c in self.palette))
        f = self.e.frame
        f.sky_top = rgb888(grade(fields["sky_top"], params))
        f.sky_horizon = rgb888(grade(fields["sky_horizon"], params))
        f.fog_color = rgb888(grade(fields["fog_color"], params))
        f.sky_span = SKY_SPAN
        fog_near, fog_far = fields["fog_near"] * 2.0, fields["fog_far"] * 2.0
        f.fog_near, f.fog_full = fog_near, fog_near + (fog_far - fog_near) * FOG_FULL
        cam = self.e.world.camera  # the far plane is the fog's end (the MCU's far clip)
        cam.near, cam.far = NEAR_PLANE, fog_far
        f.ground_fog, f.ground_top, f.ground_ramp = look[41] / 255.0, GROUND_FOG_TOP, GROUND_FOG_RAMP
        yaw, pitch = (fields[k] * 2 * math.pi / 256 for k in ("light_yaw", "light_pitch"))
        sun = (math.cos(pitch) * math.sin(yaw), math.sin(pitch), math.cos(pitch) * math.cos(yaw))
        self.light = tuple(-c for c in sun)
        f.sun.travel, f.sun.ambient, f.sun.diffuse = self.light, SUN_AMBIENT, SUN_DIFFUSE
        return grade(fields["grass_a"], params), grade(fields["grass_b"], params)

    def follow(self, cam, fog=True, hurt=False):
        """Every step: the fog on or off, the character light from just above and right of the camera
        (api.md §3.3), the red overlay while the PC is hurt."""
        f = self.e.frame
        f.fog_steps = FOG_STEPS if fog else 0
        fwd = (math.sin(cam.yaw) * math.cos(cam.pitch), math.sin(cam.pitch), math.cos(cam.yaw) * math.cos(cam.pitch))
        key = (-fwd[0] - 0.45 * math.cos(cam.yaw), -fwd[1] + 0.7, -fwd[2] + 0.45 * math.sin(cam.yaw))
        length = math.sqrt(sum(c * c for c in key))
        f.character.travel = tuple(-c / length for c in key)
        f.character.ambient, f.character.diffuse = CHAR_AMBIENT, CHAR_DIFFUSE
        f.overlay = rgba(pal.PALETTE_565[pal.HURT], HURT_ALPHA) if hurt else 0
