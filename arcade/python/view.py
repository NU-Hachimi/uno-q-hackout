"""Shows the game on alia-engine, beside what the game's own objects put in its world themselves (the rigs, the
colliders, the particles, the bullets, the hook and its rope, the dust rings: player.py, boss.py, finisher.py,
shown.py): the terrain and the scattered rocks, and the camera. The look is look.py, the HUD hud.py.

update(frame) runs every logic step (the camera, the lights); draw(frame) runs every displayed frame and draws the
HUD.
"""

import math
from array import array

import alia_engine as ae

import assets
import hud
import screen
import terrain
from look import Look, rgb888

def _hash_pick(i, j):
    """Which of the two grass tones a terrain vertex gets (sketch/render.cpp bakeTerrain)."""
    h = ((i * 73856093) & 0xFFFFFFFF) ^ ((j * 19349663) & 0xFFFFFFFF)
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h >> 16) & 1


class View:
    def __init__(self, engine, scene):
        self.e = engine
        self.scene = scene
        assets.load(engine)
        self.meshes = assets.MESHES
        self.look = Look(engine)
        self.terrain = 0
        # Terrain colours are baked with their shading (alia-engine materials, its docs/api.md §2).
        self.ground_material = engine.create_material(ae.Material(shading=ae.Shading.UNLIT, color=ae.ColorSource.VERTEX))
        self.set_sky(*terrain.blend_sky(terrain.TIME_OF_DAY[0], terrain.TIME_OF_DAY[0], 0.0))
        # What never moves: the terrain (its mesh is rebuilt when the sky changes, the node stays) and the rocks.
        engine.world.spawn(self.terrain)
        for x, z, yaw, scale, mesh_id, tint in scene.rocks:
            if mesh_id in self.meshes:
                engine.world.spawn(self.meshes[mesh_id], position=(x, terrain.terrain_height(scene, x, z), z), yaw=yaw,
                                   scale=scale, tint=tint)

    def set_sky(self, fields, look_block):
        """terrain.sky_at() output: the Look, the sky and the lights (look.py), and the terrain baked under them."""
        self._terrain_mesh(*self.look.set_sky(fields, look_block))

    def _terrain_mesh(self, grass_a, grass_b):
        s = self.scene
        n, cell, hs = s.terrain_n, s.cell, s.height_scale / 16.0
        h = s.heights

        def at(i, j):
            return h[min(max(j, 0), n - 1) * n + min(max(i, 0), n - 1)] * hs

        light = tuple(-c for c in self.look.light)  # towards the sun
        tones = [tuple((rgb888(c) >> k) & 0xFF for k in (16, 8, 0)) for c in (grass_a, grass_b)]
        pos, rgb, idx = array("f"), bytearray(), array("H")
        for j in range(n):
            for i in range(n):
                pos.extend((s.origin_x + i * cell, at(i, j), s.origin_z + j * cell))
                nx, ny, nz = at(i - 1, j) - at(i + 1, j), 2 * cell, at(i, j - 1) - at(i, j + 1)
                length = math.sqrt(nx * nx + ny * ny + nz * nz)
                shade = 0.6 + 0.4 * max(0.0, (nx * light[0] + ny * light[1] + nz * light[2]) / length)
                tone = tones[0] if _hash_pick(i, j) else tones[1]
                rgb.extend(min(255, round(c * shade)) for c in tone)
        for j in range(n - 1):
            for i in range(n - 1):
                a = j * n + i
                b, c = a + 1, a + n
                idx.extend((a, c, b, b, c, c + 1))
        mesh = ae.Mesh(pos.tobytes(), idx.tobytes(), vertex_rgb=bytes(rgb),
                       submeshes=[(0, len(idx) // 3, self.ground_material)])
        if self.terrain:
            self.e.update_mesh(self.terrain, mesh)
        else:
            self.terrain = self.e.create_mesh(mesh)

    # ---- one step and one frame -----------------------------------------------------------------
    def update(self, frame):
        """Every logic step: the camera and the lights follow this step's Frame (alia-engine interpolates)."""
        cam = frame.camera
        c = self.e.world.camera
        c.position, c.yaw, c.pitch, c.fov_x = (cam.x, cam.y, cam.z), cam.yaw, cam.pitch, math.radians(cam.fov)
        self.look.follow(cam, fog=not frame.flags & screen.FLAG_NO_FOG, hurt=bool(frame.flags & screen.FLAG_HURT))

    def draw(self, frame):
        """Every displayed frame: the HUD (the world draws itself)."""
        if not frame.flags & screen.FLAG_NO_HUD:
            hud.draw(self.e, frame.hud)
