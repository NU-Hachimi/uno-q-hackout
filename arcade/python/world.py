"""Scene generation and terrain queries shared by the game and the scene upload."""

import math

from g3d import SceneDef
from gen.palette import SCENE_DEFAULTS

TERRAIN_N = 17
CELL = 16.0        # m; 256 m square, so the 120 m fog limit never shows the map edge
HEIGHT_SCALE = 1   # 1/16 m per height unit -> heights span about +-7.9 m
ARENA_RADIUS = 30.0
HILLS_START = 70.0


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


def make_scene(seed=1, rig_id=1, slot_variants=()):
    """Rolling plain with a flat arena in the middle (the boss fight happens there)."""
    n, origin = TERRAIN_N, -(TERRAIN_N - 1) * CELL / 2
    heights = []
    for j in range(n):
        for i in range(n):
            x, z = origin + i * CELL, origin + j * CELL
            h = 5.0 * _value_noise(seed, x / 70, z / 70) + 2.0 * _value_noise(seed + 1, x / 28, z / 28)
            t = min(1.0, max(0.0, (math.hypot(x, z) - ARENA_RADIUS) / (HILLS_START - ARENA_RADIUS)))
            h *= 0.1 + 0.9 * t * t * (3 - 2 * t)
            heights.append(max(-127, min(127, round(h * 16 / HEIGHT_SCALE))))
    d = SCENE_DEFAULTS
    return SceneDef(
        heights=heights, terrain_n=n, cell=CELL, origin_x=origin, origin_z=origin, height_scale=HEIGHT_SCALE,
        sky_top=d["sky_top"], sky_horizon=d["sky_horizon"], fog_color=d["fog_color"],
        fog_near=d["fog_near"] * 2, fog_far=d["fog_far"] * 2, grass_a=d["grass_a"], grass_b=d["grass_b"],
        light_yaw=d["light_yaw"], light_pitch=d["light_pitch"], rig_id=rig_id, slot_variants=list(slot_variants))


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


def extent(scene, margin=0.0):
    """(min, max) of the playable square along both axes."""
    lo = scene.origin_x + margin
    return lo, scene.origin_x + (scene.terrain_n - 1) * scene.cell - margin
