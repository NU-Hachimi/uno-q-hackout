"""Ray and circle queries against the boss's sphere and capsule colliders (api.md §5.1)."""

import math
from dataclasses import dataclass

import rig


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _along(o, d, t):
    return o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t


def ray_sphere(o, d, c, r):
    """Distance along unit ray (o, d) to the sphere, or None. A ray starting inside returns None."""
    oc = _sub(o, c)
    b = _dot(oc, d)
    h = b * b - (_dot(oc, oc) - r * r)
    if h < 0:
        return None
    t = -b - math.sqrt(h)
    return t if t >= 0 else None


def ray_capsule(o, d, a, b, r):
    """Distance along unit ray (o, d) to the capsule a-b of radius r, or None."""
    ba, oa = _sub(b, a), _sub(o, a)
    baba, bard, baoa = _dot(ba, ba), _dot(ba, d), _dot(ba, oa)
    rdoa, oaoa = _dot(d, oa), _dot(oa, oa)
    k2 = baba - bard * bard
    if k2 > 1e-9:  # not parallel to the axis: try the cylinder wall first
        k1 = baba * rdoa - baoa * bard
        k0 = baba * oaoa - baoa * baoa - r * r * baba
        h = k1 * k1 - k2 * k0
        if h < 0:
            return None
        t = (-k1 - math.sqrt(h)) / k2
        y = baoa + t * bard
        if 0 < y < baba:
            return t if t >= 0 else None
        end = a if y <= 0 else b
    else:
        end = a if baoa + bard < 0 else b
    return ray_sphere(o, d, end, r)


@dataclass
class Collider:
    kind: str            # "body" or "part"
    shape: str           # "sphere" or "capsule"
    a: tuple             # sphere centre, or capsule end
    b: tuple             # capsule other end (== a for spheres)
    r: float
    bone: int            # bone index the collider moves with
    slot: int = -1       # rig slot for parts
    hookable: bool = False

    def centre(self):
        return tuple((x + y) / 2 for x, y in zip(self.a, self.b))

    def ray(self, o, d):
        return ray_sphere(o, d, self.a, self.r) if self.shape == "sphere" else ray_capsule(o, d, self.a, self.b, self.r)


def boss_colliders(rig_data, poses, slot_poses, alive, variants):
    """World colliders: every bone collider (kind "body"), then each fitted, alive part ("part").
    `poses` are world bone transforms; `slot_poses[i]` the world transform of slot i."""
    out = []
    for index, bone in enumerate(rig_data["bones"]):
        m = poses[index]
        for c in bone.get("colliders", []):
            if c["type"] == "sphere":
                p = rig.transform(m, c["c"])
                out.append(Collider("body", "sphere", p, p, c["r"], index, hookable=c.get("hookable", False)))
            else:
                out.append(Collider("body", "capsule", rig.transform(m, c["a"]), rig.transform(m, c["b"]), c["r"],
                                    index, hookable=c.get("hookable", False)))
    for slot_index, slot in enumerate(rig_data["slots"]):
        if not variants[slot_index] or not alive & (1 << slot_index):
            continue
        c = slot["collider"]
        p = rig.transform(slot_poses[slot_index], c["c"])
        out.append(Collider("part", "sphere", p, p, c["r"], slot["bone_index"], slot_index))
    return out


@dataclass
class Hit:
    t: float
    point: tuple
    collider: Collider


def ray_cast(o, d, colliders, max_dist, accept=lambda c: True):
    """Nearest collider hit within max_dist that `accept` allows, or None.
    Parts are tested before body shapes at equal distance, so armour on a leg wins over the leg."""
    best = None
    for c in colliders:
        if not accept(c):
            continue
        t = c.ray(o, d)
        if t is None or t > max_dist:
            continue
        if best is None or t < best.t - 1e-6 or (abs(t - best.t) <= 1e-6 and c.kind == "part"):
            best = Hit(t, _along(o, d, t), c)
    return best


def push_out(x, z, cx, cz, r):
    """Move (x, z) to the edge of the ground circle (cx, cz, r) when it is inside."""
    dx, dz = x - cx, z - cz
    dist = math.hypot(dx, dz)
    if dist >= r:
        return x, z
    if dist < 1e-6:
        dx, dz, dist = 1.0, 0.0, 1.0
    return cx + dx / dist * r, cz + dz / dist * r
