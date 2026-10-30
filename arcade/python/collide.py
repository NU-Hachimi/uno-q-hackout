"""Megalith's collision categories on alia-engine's colliders (its docs/api.md §5).

The engine holds the shapes and answers the rays (boss.py asks it); this module only says what they mean
to the game. The boss's rig carries its colliders in gen/rigs.apak, where tools/rig_build.py turns them
into layers: every bone collider is BODY (user = its bone; HOOKABLE too if the JSON says so), every part
slot's is PART (user = the slot; on while the part is fitted and unbroken, and it wins ties, so armour on
a leg beats the leg). The two hook points boss.py adds are HOOK (user = the bone they sit on)."""

import math
from dataclasses import dataclass

BODY, PART, HOOK, HOOKABLE = 1, 2, 4, 8
SOLID = BODY | PART  # what shots and sight lines stop at


@dataclass(eq=False)
class Collider:
    kind: str            # "body", "part" or "hook"
    shape: str           # "sphere" or "capsule"
    a: tuple             # sphere centre, or capsule end (world space, this step)
    b: tuple             # capsule other end (== a for spheres)
    r: float
    bone: int            # bone index the collider moves with
    slot: int = -1       # rig slot for parts
    hookable: bool = False
    node: object = None  # the engine node carrying it: the collider's identity

    @staticmethod
    def of(c, rig_data):
        """The game's view of an alia_engine.WorldCollider of the boss's rig."""
        if c.layers & PART:
            kind, bone, slot = "part", rig_data["slots"][c.user]["bone_index"], c.user
        else:
            kind, bone, slot = "hook" if c.layers & HOOK else "body", c.user, -1
        shape = c.shape.name.lower()  # alia_engine.Shape: "sphere" or "capsule"
        return Collider(kind, shape, c.a, c.b, c.r, bone, slot, bool(c.layers & (HOOK | HOOKABLE)), c.node)

    def centre(self):
        return tuple((x + y) / 2 for x, y in zip(self.a, self.b))

    def __eq__(self, other):
        return isinstance(other, Collider) and self.node == other.node

    def __hash__(self):
        return hash(self.node)


@dataclass
class Hit:
    t: float
    point: tuple
    collider: Collider


def push_out(x, z, cx, cz, r):
    """Move (x, z) to the edge of the ground circle (cx, cz, r) when it is inside."""
    dx, dz = x - cx, z - cz
    dist = math.hypot(dx, dz)
    if dist >= r:
        return x, z
    if dist < 1e-6:
        dx, dz, dist = 1.0, 0.0, 1.0
    return cx + dx / dist * r, cz + dz / dist * r
