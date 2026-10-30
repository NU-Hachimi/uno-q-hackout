"""Rig pose evaluation (docs/api.md §5.1). The MCU's sketch/rig.cpp must give the same result;
tests/golden/rig_<name>.json, written from this module, is the reference for both.

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
    # Unrolled (the hot spot on the board); same sums in the same order as the generator form.
    (a00, a01, a02), (a10, a11, a12), (a20, a21, a22) = a
    (b00, b01, b02), (b10, b11, b12), (b20, b21, b22) = b
    return ((a00 * b00 + a01 * b10 + a02 * b20, a00 * b01 + a01 * b11 + a02 * b21, a00 * b02 + a01 * b12 + a02 * b22),
            (a10 * b00 + a11 * b10 + a12 * b20, a10 * b01 + a11 * b11 + a12 * b21, a10 * b02 + a11 * b12 + a12 * b22),
            (a20 * b00 + a21 * b10 + a22 * b20, a20 * b01 + a21 * b11 + a22 * b21, a20 * b02 + a21 * b12 + a22 * b22))


def _apply3(m, v):
    (m00, m01, m02), (m10, m11, m12), (m20, m21, m22) = m
    x, y, z = v
    return (m00 * x + m01 * y + m02 * z, m10 * x + m11 * y + m12 * z, m20 * x + m21 * y + m22 * z)


def euler(rx, ry, rz):
    """R = Ry(ry) · Rx(rx) · Rz(rz), degrees (yaw, then pitch, then roll)."""
    return _mul3(_mul3(_ry(ry), _rx(rx)), _rz(rz))


def compose(a, b):
    """a · b: apply b first, then a."""
    (tx, ty, tz), (ux, uy, uz) = _apply3(a[0], b[1]), a[1]
    return _mul3(a[0], b[0]), (tx + ux, ty + uy, tz + uz)


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


# Poses by (rig id, animation, phase). Phases are bytes, so there are at most 256 per animation
# (a few thousand in all); the game asks for the same pose several times per frame (colliders,
# saddle, hand, drawing), and pure-Python matrix maths is the hot spot on the board's A53.
_POSES = {}


def pose(rig, anim_id, phase):
    """Rig-space transform of every bone for animation `anim_id` at `phase` (0..255); a tuple, shared
    between callers, so do not modify it."""
    if not isinstance(phase, int):
        return tuple(_pose(rig, anim_id, phase))
    key = (rig["id"], anim_id, phase)
    poses = _POSES.get(key)
    if poses is None:
        poses = _POSES[key] = tuple(_pose(rig, anim_id, phase))
    return poses


def _pose(rig, anim_id, phase):
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


_SLOT_LOCAL = {}  # (rig id, slot) -> the slot's fixed offset and rotation in its bone's frame


def slot_matrix(rig, poses, slot_index):
    slot = rig["slots"][slot_index]
    key = (rig["id"], slot_index)
    local = _SLOT_LOCAL.get(key)
    if local is None:
        local = _SLOT_LOCAL[key] = compose(translate(slot["offset"]), rotate(*slot["rot"]))
    return compose(poses[slot["bone_index"]], local)


def attach_matrix(rig, poses, name):
    """Rig-space transform of a named `attach` point (the horse's saddle, the rider's hand)."""
    point = rig["attach"][name]
    return compose(poses[point["bone_index"]], translate(point["offset"]))


def rig_to_world(x, y, z, yaw):
    """T(pos) · Ry(yaw), with yaw in radians like every other g3d angle."""
    return _ry(math.degrees(yaw)), (x, y, z)


def world_poses(rig, anim_id, phase, x, y, z, yaw):
    base = rig_to_world(x, y, z, yaw)
    return [compose(base, m) for m in pose(rig, anim_id, phase)]
