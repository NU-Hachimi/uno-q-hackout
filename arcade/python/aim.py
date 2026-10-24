"""The reticle: aim assist towards parts and hook points, and its position on the 240x160 screen."""

import math
from dataclasses import dataclass

import camera
import collide

ASSIST_DEG = 4.0                     # snap to a target within this angle of the screen centre
FOCAL = 120 / math.tan(math.radians(camera.FOV / 2))  # px; the MCU's projection (fovX, 240 wide)
MAX_OFFSET = 254                     # px; the frame packet sends the offset in 2 px units (i8)
FLAG_PART, FLAG_HOOK = 1, 2          # reticle_flags (api.md §3.3)
HOOK_RANGE = 25.0                    # m from the PC's hand (player.HOOK_RANGE)


@dataclass
class Aim:
    origin: tuple            # camera position
    direction: tuple         # unit vector a shot fired now travels
    dx: int = 0              # reticle offset from the screen centre, px (right, down)
    dy: int = 0
    flags: int = 0
    target: object = None    # part collide.Collider the reticle sits on, if any
    hook: object = None      # collide.Hit where the hook would catch, if in range


def basis(view):
    f = camera.forward(view.yaw, view.pitch)
    r = camera.right(view.yaw)
    u = (r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0])  # r x f
    return f, r, u


def project(view, point):
    """Screen offset (dx, dy) in px of a world point, or None when it is behind the camera."""
    f, r, u = basis(view)
    v = (point[0] - view.x, point[1] - view.y, point[2] - view.z)
    z = sum(a * b for a, b in zip(v, f))
    if z <= 0.1:
        return None
    return (sum(a * b for a, b in zip(v, r)) / z * FOCAL, -sum(a * b for a, b in zip(v, u)) / z * FOCAL)


def _towards(origin, point):
    v = tuple(b - a for a, b in zip(origin, point))
    dist = math.sqrt(sum(x * x for x in v))
    return tuple(x / dist for x in v), dist


def _visible(origin, target, colliders):
    d, dist = _towards(origin, target.centre())
    hit = collide.ray_cast(origin, d, colliders, dist + target.r)
    return hit is not None and hit.collider is target


def _snap(origin, f, colliders, wants):
    """The wanted, visible collider closest to the screen centre within ASSIST_DEG, or None."""
    best, best_angle = None, math.radians(ASSIST_DEG)
    for c in colliders:
        if not wants(c):
            continue
        d, dist = _towards(origin, c.centre())
        if dist < 1e-6:
            continue
        angle = math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(d, f)))))
        if angle < best_angle and _visible(origin, c, colliders):
            best, best_angle = c, angle
    return best


def compute(view, colliders, hand=None):
    """Where the reticle sits this frame, where a shot would go, and where the hook would catch."""
    origin = (view.x, view.y, view.z)
    f, _, _ = basis(view)
    aim = Aim(origin, f)

    part = _snap(origin, f, colliders, lambda c: c.kind == "part")
    if part is not None:
        aim.direction, _ = _towards(origin, part.centre())
        aim.target, aim.flags = part, FLAG_PART
    else:
        hit = collide.ray_cast(origin, f, colliders, 200.0)
        if hit is not None and hit.collider.kind == "part":
            aim.target, aim.flags = hit.collider, FLAG_PART

    hook_target = None
    if hand is not None:
        hook_target = _snap(origin, f, colliders, lambda c: c.hookable)
        d = _towards(origin, hook_target.centre())[0] if hook_target is not None else f
        hit = collide.ray_cast(origin, d, colliders, 200.0)
        if hit is not None and hit.collider.hookable and math.dist(hand, hit.point) <= HOOK_RANGE:
            aim.hook, aim.flags = hit, aim.flags | FLAG_HOOK

    snapped = part if part is not None else (hook_target if aim.hook is not None else None)
    if snapped is not None:
        offset = project(view, snapped.centre()) or (0.0, 0.0)
        aim.dx, aim.dy = (max(-MAX_OFFSET, min(MAX_OFFSET, round(p))) for p in offset)
    return aim
