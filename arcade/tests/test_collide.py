import math

import collide


def test_ray_sphere_hit_miss_and_inside():
    assert abs(collide.ray_sphere((0, 0, -10), (0, 0, 1), (0, 0, 0), 2) - 8) < 1e-9
    assert collide.ray_sphere((0, 3, -10), (0, 0, 1), (0, 0, 0), 2) is None
    assert collide.ray_sphere((0, 0, 0), (0, 0, 1), (0, 0, 0), 2) is None  # starts inside


def test_ray_capsule_wall_and_caps():
    a, b, r = (0, 0, 0), (0, 4, 0), 1.0
    assert abs(collide.ray_capsule((-5, 2, 0), (1, 0, 0), a, b, r) - 4) < 1e-9   # side wall
    assert abs(collide.ray_capsule((0, 10, 0), (0, -1, 0), a, b, r) - 5) < 1e-9  # top cap, along the axis
    t = collide.ray_capsule((-5, -0.5, 0), (1, 0, 0), a, b, r)                   # bottom hemisphere
    assert abs(t - (5 - math.sqrt(1 - 0.25))) < 1e-9
    assert collide.ray_capsule((-5, 6, 0), (1, 0, 0), a, b, r) is None


def test_ray_cast_prefers_nearest_and_filters():
    near = collide.Collider("body", "sphere", (0, 0, 5), (0, 0, 5), 1, 0)
    far = collide.Collider("part", "sphere", (0, 0, 10), (0, 0, 10), 1, 0, slot=2)
    hit = collide.ray_cast((0, 0, 0), (0, 0, 1), [far, near], 100)
    assert hit.collider is near and abs(hit.t - 4) < 1e-9
    hit = collide.ray_cast((0, 0, 0), (0, 0, 1), [far, near], 100, accept=lambda c: c.kind == "part")
    assert hit.collider is far
    assert collide.ray_cast((0, 0, 0), (0, 0, 1), [far], 5) is None


def test_push_out():
    assert collide.push_out(5, 0, 0, 0, 1) == (5, 0)
    x, z = collide.push_out(0.5, 0, 0, 0, 1)
    assert abs(x - 1) < 1e-9 and z == 0
