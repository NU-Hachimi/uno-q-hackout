"""Rig pose evaluation (docs/api.md §5.1): the reference implementation. The game itself poses its rigs in
alia-engine; tools/rig_build.py writes tests/golden/rig_<name>.json from this module, and both the engine
(tests/test_alia.py) and the MCU's sketch/rig.cpp are checked against those files. Plain and readable on
purpose: nothing runs it per frame any more.

Affine transforms are (R, t): R a 3x3 row-major tuple of rows, t a 3-tuple; they map p -> R p + t.
Rig space has its origin on the ground under the boss; world = T(rig pos) · Ry(rig yaw) · rig space.
"""

import math

IDENTITY = (((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))


def _rx(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _ry(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def _rz(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _mul3(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _apply3(m, v):
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3))


def euler(rx, ry, rz):
    """R = Ry(ry) · Rx(rx) · Rz(rz), degrees (yaw, then pitch, then roll)."""
    return _mul3(_mul3(_ry(ry), _rx(rx)), _rz(rz))


def compose(a, b):
    """a · b: apply b first, then a."""
    return _mul3(a[0], b[0]), tuple(x + y for x, y in zip(_apply3(a[0], b[1]), a[1]))


def transform(m, p):
    return tuple(x + y for x, y in zip(_apply3(m[0], p), m[1]))


def transform_dir(m, v):
    return _apply3(m[0], v)


def inverse(m):
    """Inverse of a rigid transform (rotation + translation)."""
    r = tuple(tuple(m[0][j][i] for j in range(3)) for i in range(3))
    return r, tuple(-c for c in _apply3(r, m[1]))


def translate(t):
    return IDENTITY[0], tuple(t)


def rotate(rx, ry, rz):
    return euler(rx, ry, rz), (0.0, 0.0, 0.0)


def key_position(anim, phase):
    """(i, j, t): blend key i towards key j by t, for phase 0..255."""
    keys = anim["keys"]
    if keys == 1:
        return 0, 0, 0.0
    if anim["loop"]:
        f = phase * keys / 256.0
        i = int(f)
        return i, (i + 1) % keys, f - i
    f = phase * (keys - 1) / 255.0
    i = min(int(f), keys - 2)
    return i, i + 1, f - i


def _lerp(a, b, t):
    return a + (b - a) * t


def pose(rig, anim_id, phase):
    """Rig-space transform of every bone for animation `anim_id` at `phase` (0..255)."""
    anim = rig["anims"][anim_id]
    i, j, t = key_position(anim, phase)
    out = []
    for index, bone in enumerate(rig["bones"]):
        track = anim["tracks"].get(bone["name"])
        if track:
            angles = [_lerp(track[i][k], track[j][k], t) for k in range(3)]
            local_r = euler(*angles)
        else:
            local_r = IDENTITY[0]
        offset = list(bone["offset"])
        if bone["parent"] is None and anim.get("root_y"):
            offset[1] += _lerp(anim["root_y"][i], anim["root_y"][j], t)
        local = (local_r, tuple(offset))
        parent = bone["parent_index"]
        out.append(local if parent < 0 else compose(out[parent], local))
    return out


def slot_matrix(rig, poses, slot_index):
    slot = rig["slots"][slot_index]
    return compose(poses[slot["bone_index"]], compose(translate(slot["offset"]), rotate(*slot["rot"])))


def attach_matrix(rig, poses, name):
    """Rig-space transform of a named `attach` point (the horse's saddle, the rider's hand)."""
    point = rig["attach"][name]
    return compose(poses[point["bone_index"]], translate(point["offset"]))


def rig_to_world(x, y, z, yaw):
    """T(pos) · Ry(yaw), with yaw in radians like every other angle in the game."""
    return _ry(math.degrees(yaw)), (x, y, z)


def world_poses(rig, anim_id, phase, x, y, z, yaw):
    base = rig_to_world(x, y, z, yaw)
    return [compose(base, m) for m in pose(rig, anim_id, phase)]
