import world


def test_scene_shape_and_defaults():
    scene = world.make_scene(1)
    assert len(scene.heights) == scene.terrain_n ** 2
    assert all(-127 <= h <= 127 for h in scene.heights)
    lo, hi = world.extent(scene)
    assert (lo, hi) == (-128.0, 128.0)
    assert scene.fog_far == 120 and scene.fog_near == 40


def test_arena_is_flat():
    scene = world.make_scene(3)
    heights = [world.terrain_height(scene, x, z) for x in range(-20, 21, 5) for z in range(-20, 21, 5)]
    assert max(heights) - min(heights) < 2.0


def test_terrain_height_matches_grid_and_interpolates():
    scene = world.make_scene(2)
    n, cell, o = scene.terrain_n, scene.cell, scene.origin_x
    for j, i in ((0, 0), (5, 7), (16, 16)):
        assert abs(world.terrain_height(scene, o + i * cell, o + j * cell) - scene.heights[j * n + i] / 16) < 1e-9
    a = world.terrain_height(scene, o + 3 * cell, o + 4 * cell)
    b = world.terrain_height(scene, o + 4 * cell, o + 4 * cell)
    assert abs(world.terrain_height(scene, o + 3.5 * cell, o + 4 * cell) - (a + b) / 2) < 1e-9
    assert world.terrain_height(scene, -1e6, -1e6) == scene.heights[0] / 16  # clamped to the edge
