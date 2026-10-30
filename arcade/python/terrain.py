"""Scene generation and terrain queries: the terrain, the rocks, the day cycle."""

import math
import random
import struct
from dataclasses import dataclass, field

from gen import mesh_ids
from gen.looks import LOOKS
from gen.palette import SCENE_DEFAULTS

@dataclass
class SceneDef:
    heights: list            # terrain_n² ints in -127..127, row-major (z rows, x columns)
    terrain_n: int = 17
    cell: float = 16.0       # m
    origin_x: float = -128.0  # m, corner of vertex (0, 0)
    origin_z: float = -128.0
    height_scale: int = 1    # 1/16 m per height unit
    sky_top: int = 0
    sky_horizon: int = 0
    fog_color: int = 0
    fog_near: float = 40.0   # m
    fog_far: float = 120.0   # m, also the far clip plane
    grass_a: int = 0
    grass_b: int = 0
    light_yaw: int = 0       # BAM8
    light_pitch: int = 0     # BAM8
    rig_id: int = 0
    slot_variants: list = field(default_factory=list)
    rocks: list = field(default_factory=list)  # (x, z, yaw_rad, scale, mesh_id, tint)
    look: bytes = b""        # 76 B Look block (gen/looks.py), or empty for the default


TERRAIN_N = 17
CELL = 16.0        # m; 256 m square, so the 120 m fog limit never shows the map edge
HEIGHT_SCALE = 1   # 1/16 m per height unit -> heights span about +-7.9 m
ARENA_RADIUS = 30.0
HILLS_START = 70.0

# Day cycle: noon -> dusk -> night -> dawn -> noon (assets/looks/). Each time of day holds DAY_HOLD s, then
# blends into the next over DAY_BLEND s. Short test values: one day is 4 * (12 + 8) = 80 s.
TIME_OF_DAY = ("forbidden_plain", "dusk", "night", "dawn")
DAY_HOLD = 12.0
DAY_BLEND = 8.0
SKY_COLORS = ("sky_top", "sky_horizon", "fog_color", "grass_a", "grass_b")  # RGB565
SKY_NUMBERS = ("fog_near", "fog_far", "light_pitch")                       # 2 m units, BAM8
_LOOK = struct.Struct("<32HBBBbBHHBBB")

# Scattered scenery outside the arena: (mesh, weight, min scale, max scale).
SCENERY = ((mesh_ids.ROCK_A, 4, 1.0, 2.6), (mesh_ids.ROCK_B, 4, 1.0, 2.4),
           (mesh_ids.PILLAR_BROKEN, 2, 0.9, 1.4), (mesh_ids.ARCH_FRAGMENT, 1, 1.0, 1.4))
ROCK_COUNT = 40
ROCK_NEAR, ROCK_FAR = ARENA_RADIUS + 6, 118.0  # m from the centre


def _lattice(seed, x, z):
    h = (seed ^ (x * 374761393) ^ (z * 668265263)) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 32767.5 - 1.0


def _value_noise(seed, x, z):
    x0, z0 = math.floor(x), math.floor(z)
    fx, fz = x - x0, z - z0
    fx, fz = fx * fx * (3 - 2 * fx), fz * fz * (3 - 2 * fz)
    a, b = _lattice(seed, x0, z0), _lattice(seed, x0 + 1, z0)
    c, d = _lattice(seed, x0, z0 + 1), _lattice(seed, x0 + 1, z0 + 1)
    top, bottom = a + (b - a) * fx, c + (d - c) * fx
    return top + (bottom - top) * fz


def scatter_rocks(seed):
    """(x, z, yaw, scale, mesh_id, tint) for every rock, deterministic for a seed."""
    rng = random.Random(seed * 7919 + 3)
    weights = [w for _, w, _, _ in SCENERY]
    rocks = []
    for _ in range(ROCK_COUNT):
        mesh, _, lo, hi = rng.choices(SCENERY, weights)[0]
        angle = rng.uniform(0, 2 * math.pi)
        dist = ROCK_NEAR + (ROCK_FAR - ROCK_NEAR) * rng.random() ** 0.8
        rocks.append((dist * math.sin(angle), dist * math.cos(angle), rng.uniform(0, 2 * math.pi),
                      rng.uniform(lo, hi), mesh, 0))
    return rocks


def _lerp565(a, b, k):
    ch = [((a >> s) & m) + (((b >> s) & m) - ((a >> s) & m)) * k for s, m in ((11, 31), (5, 63), (0, 31))]
    return (round(ch[0]) << 11) | (round(ch[1]) << 5) | round(ch[2])


def sky_fields(look):
    d = dict(SCENE_DEFAULTS)
    d.update(LOOKS[look]["scene"])
    return {k: d[k] for k in SKY_COLORS + SKY_NUMBERS + ("light_yaw",)}


def blend_sky(a, b, k):
    """Blend two Looks (and their scene colours) by k in 0..1 -> (fields, 76 B Look block)."""
    fa, fb = sky_fields(a), sky_fields(b)
    fields = {c: _lerp565(fa[c], fb[c], k) for c in SKY_COLORS}
    fields.update({n: round(fa[n] + (fb[n] - fa[n]) * k) for n in SKY_NUMBERS})
    turn = (fb["light_yaw"] - fa["light_yaw"] + 128) % 256 - 128  # the sun takes the short way round
    fields["light_yaw"] = round(fa["light_yaw"] + turn * k) % 256
    la, lb = _LOOK.unpack(LOOKS[a]["block"]), _LOOK.unpack(LOOKS[b]["block"])
    palette = [_lerp565(p, q, k) for p, q in zip(la[:32], lb[:32])]
    mode, sat, con, bri, gam = (round(p + (q - p) * k) for p, q in zip(la[32:37], lb[32:37]))
    lift, gain = (_lerp565(p, q, k) for p, q in zip(la[37:39], lb[37:39]))
    post, dith = (la if k < 0.5 else lb)[39:41]
    ground = round(la[41] + (lb[41] - la[41]) * k)
    return fields, _LOOK.pack(*palette, mode, sat, con, bri, gam, lift, gain, post, dith, ground)


def sky_at(seconds):
    """Day-cycle sky at `seconds` -> (fields, Look block)."""
    n, period = len(TIME_OF_DAY), DAY_HOLD + DAY_BLEND
    i = int(seconds // period) % n
    t = (seconds % period - DAY_HOLD) / DAY_BLEND
    k = 0.0 if t <= 0 else t * t * (3 - 2 * t)
    return blend_sky(TIME_OF_DAY[i], TIME_OF_DAY[(i + 1) % n], k)


def make_scene(seed=1, rig_id=1, slot_variants=(), look="forbidden_plain"):
    """Rolling plain with a flat arena in the middle (the boss fight happens there), lit by `look`."""
    n, origin = TERRAIN_N, -(TERRAIN_N - 1) * CELL / 2
    heights = []
    for j in range(n):
        for i in range(n):
            x, z = origin + i * CELL, origin + j * CELL
            h = 5.0 * _value_noise(seed, x / 70, z / 70) + 2.0 * _value_noise(seed + 1, x / 28, z / 28)
            t = min(1.0, max(0.0, (math.hypot(x, z) - ARENA_RADIUS) / (HILLS_START - ARENA_RADIUS)))
            h *= 0.1 + 0.9 * t * t * (3 - 2 * t)
            heights.append(max(-127, min(127, round(h * 16 / HEIGHT_SCALE))))
    d = dict(SCENE_DEFAULTS)
    d.update(LOOKS[look]["scene"])
    return SceneDef(
        heights=heights, terrain_n=n, cell=CELL, origin_x=origin, origin_z=origin, height_scale=HEIGHT_SCALE,
        sky_top=d["sky_top"], sky_horizon=d["sky_horizon"], fog_color=d["fog_color"],
        fog_near=d["fog_near"] * 2, fog_far=d["fog_far"] * 2, grass_a=d["grass_a"], grass_b=d["grass_b"],
        light_yaw=d["light_yaw"], light_pitch=d["light_pitch"], rig_id=rig_id, slot_variants=list(slot_variants),
        rocks=scatter_rocks(seed), look=LOOKS[look]["block"])


def terrain_height(scene, x, z):
    """Bilinear, clamped to the edge; must match scene::terrainHeight in the sketch."""
    n = scene.terrain_n
    gx = min(max((x - scene.origin_x) / scene.cell, 0.0), n - 1)
    gz = min(max((z - scene.origin_z) / scene.cell, 0.0), n - 1)
    i, j = min(int(gx), n - 2), min(int(gz), n - 2)
    fx, fz = gx - i, gz - j
    h = scene.heights
    top = h[j * n + i] + (h[j * n + i + 1] - h[j * n + i]) * fx
    bottom = h[(j + 1) * n + i] + (h[(j + 1) * n + i + 1] - h[(j + 1) * n + i]) * fx
    return (top + (bottom - top) * fz) * scene.height_scale / 16


def set_ground(w, scene):
    """The terrain as alia-engine's ground (heights in m, the same bilinear surface as terrain_height):
    shots stop on it (World.ray_ground)."""
    k = scene.height_scale / 16
    w.set_ground([h * k for h in scene.heights], scene.terrain_n, scene.cell, (scene.origin_x, scene.origin_z))


def extent(scene, margin=0.0):
    """(min, max) of the playable square along both axes."""
    lo = scene.origin_x + margin
    return lo, scene.origin_x + (scene.terrain_n - 1) * scene.cell - margin
