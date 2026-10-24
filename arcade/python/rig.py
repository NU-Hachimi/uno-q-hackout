"""Rig poses (docs/api.md §5.1). This is the reference: sketch/rig.cpp must match it within 1 cm
(tests/golden/rig_*.json, checked by tests/test_rig.py and tests/cpp/rig_golden.sh).

Pure Python (the board has no numpy). A transform is (R, t): R a 3x3 row-major tuple, t a 3-tuple.
"""

import math


def rot(rx, ry, rz):
    """Track triplet [rx, ry, rz] in degrees, applied yaw -> pitch -> roll: R = Ry · Rx · Rz."""
    x, y, z = math.radians(rx), math.radians(ry), math.radians(rz)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    # Ry·Rx·Rz expanded
    return ((cy * cz + sy * sx * sz, -cy * sz + sy * sx * cz, sy * cx),
            (cx * sz, cx * cz, -sx),
            (-sy * cz + cy * sx * sz, sy * sz + cy * sx * cz, cy * cx))


IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def apply(xf, p):
    (r, t) = xf
    return tuple(r[i][0] * p[0] + r[i][1] * p[1] + r[i][2] * p[2] + t[i] for i in range(3))


def compose(a, b):
    """a · b."""
    ra, ta = a
    rb, tb = b
    r = tuple(tuple(sum(ra[i][k] * rb[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    return r, apply(a, tb)


def sample(keys, phase, loop):
    """Linear interpolation of keys spread over phase: loop -> 0..256 wrapping, else 0..255 end to end."""
    n = len(keys)
    if n == 1:
        return keys[0]
    f = phase * n / 256 if loop else phase * (n - 1) / 255
    i = int(f)
    t = f - i
    a = keys[i % n]
    b = keys[(i + 1) % n] if loop else keys[min(i + 1, n - 1)]
    if isinstance(a, (int, float)):
        return a + (b - a) * t
    return [ka + (kb - ka) * t for ka, kb in zip(a, b)]


def anim_index(rig, anim):
    if isinstance(anim, int):
        return anim
    return next(a["id"] for a in rig["anims"] if a["name"] == anim)


def pose(rig, anim, phase):
    """Bone name -> transform in rig space (rig origin at 0, yaw 0)."""
    an = rig["anims"][anim_index(rig, anim)]
    loop, tracks = an["loop"], an.get("tracks", {})
    out = {}
    for b in rig["bones"]:
        r = rot(*sample(tracks[b["name"]], phase, loop)) if b["name"] in tracks else IDENTITY
        off = list(b["offset"])
        if b["parent"] is None:
            if "root_y" in an:
                off[1] += sample(an["root_y"], phase, loop)
            out[b["name"]] = (r, tuple(off))
        else:
            out[b["name"]] = compose(out[b["parent"]], (r, tuple(off)))
    return out


def placement(x, y, z, yaw):
    """Rig block origin: T(x, y, z) · Ry(yaw)."""
    c, s = math.cos(yaw), math.sin(yaw)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c)), (x, y, z)


def attach(rig, name, anim, phase, x=0.0, y=0.0, z=0.0, yaw=0.0):
    """World position of an `attach` point for a rig placed at (x, y, z, yaw)."""
    a = rig["attach"][name]
    bone = pose(rig, anim, phase)[a["bone"]]
    return apply(compose(placement(x, y, z, yaw), bone), a["offset"])
