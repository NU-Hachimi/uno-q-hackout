"""The reticle: aim assist towards parts and hook points, and its position on the 240x160 screen."""

import math
from dataclasses import dataclass

import camera
import collide

ASSIST_DEG = 4.0                     # snap to a target within this angle of the screen centre
HOOK_ASSIST_DEG = 6.0                # hook points are small: the hook snaps to them from a little further out
HOOK_SURFACE = 1.5                   # m; the boss's own surface this close before a hook point does not block it
FOCAL = 120 / math.tan(math.radians(camera.FOV / 2))  # px; the MCU's projection (fovX, 240 wide)
MAX_OFFSET = 254                     # px at 240x160: how far the reticle may move off the centre
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


def _visible(origin, target, boss):
    d, dist = _towards(origin, target.centre())
    hit = boss.ray_cast(origin, d, dist + target.r)
    return hit is not None and hit.collider == target


def _snap(origin, f, boss, wants):
    """The wanted, visible collider closest to the screen centre within ASSIST_DEG, or None."""
    best, best_angle = None, math.radians(ASSIST_DEG)
    for c in boss.colliders():
        if not wants(c):
            continue
        d, dist = _towards(origin, c.centre())
        if dist < 1e-6:
            continue
        angle = math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(d, f)))))
        if angle < best_angle and _visible(origin, c, boss):
            best, best_angle = c, angle
    return best


def _hook_clear(origin, hook, boss):
    """Nothing stands between the camera and the hook point but the bone it sits on (the brow sits among
    the skull, snout and antlers; the hump on the torso) and the boss's surface right around it."""
    d, dist = _towards(origin, hook.centre())
    hit = boss.ray_cast(origin, d, dist, exclude_bone=hook.bone)
    return hit is None or hit.t >= dist - HOOK_SURFACE


def compute(view, boss, hand=None):
    """Where the reticle sits this frame, where a shot would go, and where the hook would catch (on the
    boss's hook points, Boss.hook_targets(), only; `hand` is where the hook leaves from, None: no hook)."""
    origin = (view.x, view.y, view.z)
    f, _, _ = basis(view)
    aim = Aim(origin, f)

    part = _snap(origin, f, boss, lambda c: c.kind == "part")
    if part is not None:
        aim.direction, _ = _towards(origin, part.centre())
        aim.target, aim.flags = part, FLAG_PART
    else:
        hit = boss.ray_cast(origin, f, 200.0)
        if hit is not None and hit.collider.kind == "part":
            aim.target, aim.flags = hit.collider, FLAG_PART

    best = math.radians(HOOK_ASSIST_DEG)
    hooks = boss.hook_targets() if hand is not None else ()
    under = boss.ray_cast(origin, f, 1000.0, layers=collide.HOOK) if hooks else None  # the hook point the reticle is on
    for hook in hooks:
        d, dist = _towards(origin, hook.centre())
        angle = math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(d, f)))))
        if under is not None and under.collider == hook:
            angle = 0.0
        if angle <= best and math.dist(hand, hook.centre()) <= HOOK_RANGE and _hook_clear(origin, hook, boss):
            best, aim.hook = angle, collide.Hit(dist, hook.centre(), hook)
    if aim.hook is not None:
        aim.flags |= FLAG_HOOK

    snapped = part if part is not None else (aim.hook.collider if aim.hook is not None else None)
    if snapped is not None:
        offset = project(view, snapped.centre()) or (0.0, 0.0)
        aim.dx, aim.dy = (max(-MAX_OFFSET, min(MAX_OFFSET, round(p))) for p in offset)
    return aim
