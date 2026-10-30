"""Shows the game on alia-engine, beside what the game's own objects already put in its world (the rigs, the
colliders, the particles): the terrain and the scattered rocks, the objects that come and go with each step's
Frame (bullets, the hook head, dust rings, the finisher's flash), the rope, and the camera. The look is look.py,
the HUD hud.py.

update(frame, hand) runs every logic step and keeps the world in step with the Frame (the engine interpolates
between steps); draw(frame) runs every displayed frame and draws the HUD.
"""

import math
from array import array

import alia_engine as ae

import assets
import hud
import screen
import terrain
from gen import palette as pal
from look import Look, rgb888

ROPE_HALF_WIDTH = 0.06     # m


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
        self.rope = 0
        self.terrain = 0
        # Terrain colours are baked with their shading; the rope is a flat ribbon that never sinks into
        # the ground fog (alia-engine materials, its docs/api.md §2).
        self.ground_material = engine.create_material(ae.Material(shading=ae.Shading.UNLIT, color=ae.ColorSource.VERTEX))
        self.rope_material = engine.create_material(ae.Material(shading=ae.Shading.UNLIT, color=ae.ColorSource.VERTEX,
                                                                double_sided=True, ground_fog=False))
        self.set_sky(*terrain.blend_sky(terrain.TIME_OF_DAY[0], terrain.TIME_OF_DAY[0], 0.0))
        # What never moves: the terrain (its mesh is rebuilt when the sky changes, the node stays) and the rocks.
        engine.world.spawn(self.terrain)
        self.pool = {}       # mesh id -> nodes for this kind of object
        self.rope_node = None
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
    def update(self, frame, hand=None):
        """Every logic step: the world follows this step's Frame (alia-engine interpolates between steps);
        `hand`, the rider's hand, is where the rope starts."""
        cam = frame.camera
        c = self.e.world.camera
        c.position, c.yaw, c.pitch, c.fov_x = (cam.x, cam.y, cam.z), cam.yaw, cam.pitch, math.radians(cam.fov)
        self.look.follow(cam, fog=not frame.flags & screen.FLAG_NO_FOG, hurt=bool(frame.flags & screen.FLAG_HURT))
        self._objects(frame.objects)
        self._rope(frame.hook, hand, cam)

    def draw(self, frame):
        """Every displayed frame: the HUD (the world draws itself)."""
        if not frame.flags & screen.FLAG_NO_HUD:
            hud.draw(self.e, frame.hud)

    def _objects(self, objects):
        """Bullets, the hook head, dust rings, the finisher's flash: pooled nodes by mesh (sparks and debris are
        particles, effects.py). Objects have no identity from
        one Frame to the next, so they are placed without blending (teleport)."""
        used = {}
        for o in objects:
            handle = self.meshes.get(o.mesh)
            if not handle:
                continue
            nodes = self.pool.setdefault(o.mesh, [])
            n = used.get(o.mesh, 0)
            if n == len(nodes):
                nodes.append(self.e.world.spawn(handle))
            node = nodes[n]
            used[o.mesh] = n + 1
            node.position, node.scale = (o.x, o.y, o.z), o.scale
            node.set_rotation(o.yaw, o.pitch, 0.0)
            node.tint, node.ground_fog, node.visible = o.tint, o.tint != pal.FLASH, True
            node.teleport()
        for mesh_id, nodes in self.pool.items():
            for node in nodes[used.get(mesh_id, 0):]:
                node.visible = False

    def _rope(self, hook, hand, cam):
        """A camera-facing strip from the rider's hand to the hook head (api.md §3.3 Hook block)."""
        show = bool(hook.flags & 1) and hand is not None
        if show:
            anchor, eye = (hook.x, hook.y, hook.z), (cam.x, cam.y, cam.z)
            along = [b - a for a, b in zip(hand, anchor)]
            mid = [(a + b) / 2 - c for a, b, c in zip(hand, anchor, eye)]
            side = (along[1] * mid[2] - along[2] * mid[1], along[2] * mid[0] - along[0] * mid[2],
                    along[0] * mid[1] - along[1] * mid[0])
            length = math.sqrt(sum(c * c for c in side))
            show = length >= 1e-6
        if not show:
            if self.rope_node:
                self.rope_node.visible = False
            return
        side = [c * ROPE_HALF_WIDTH / length for c in side]
        quad = []
        for end in (hand, anchor):
            for k in (1, -1):
                quad.extend(c + s * k for c, s in zip(end, side))
        color = rgb888(self.look.palette[pal.ROPE]).to_bytes(3, "big") * 4
        mesh = ae.Mesh(array("f", quad).tobytes(), array("H", (0, 1, 2, 2, 1, 3)).tobytes(), vertex_rgb=color,
                       submeshes=[(0, 2, self.rope_material)])
        if self.rope:
            self.e.update_mesh(self.rope, mesh)
        else:
            self.rope = self.e.create_mesh(mesh)
            self.rope_node = self.e.world.spawn(self.rope)
        self.rope_node.visible = True
