"""Shows a game Frame with alia-engine: the Alia Pad replacement for the MCU renderer (sketch/render.cpp).

Same picture semantics as the MCU (docs/api.md §3, art.md §4): palette meshes graded by the Look, banded
distance fog, ground fog, the character light, fades, the hook rope and the HUD; at 640x360 instead of
240x160, with the same horizontal field of view. The game code (game.py and below) does not know about it.

Two halves (docs/alia-port.md): update(frame) runs in every logic step and keeps alia-engine's world in
step with the Frame (the three rigs as engine rigs, the objects as pooled nodes, the camera, the rope), so
the engine interpolates them; draw(frame) runs every displayed frame and only draws the HUD.
"""

import math
import struct
from array import array
from pathlib import Path

import alia_engine as ae

import g3d
import world
from gen import mesh_ids
from gen import palette as pal

MESH_PACK = Path(__file__).resolve().parent / "gen" / "meshes.apak"  # alia-engine resource pack (tools/mesh_build.py)
_LOOK = struct.Struct("<32HBBBbBHHBBB")

# Lights and materials (sketch/render.cpp).
SUN_AMBIENT, SUN_DIFFUSE, CHAR_AMBIENT, CHAR_DIFFUSE = 0.5, 0.65, 0.55, 0.6
NEAR_PLANE = 0.5
FOG_STEPS = 16
FOG_FULL = 0.92            # fully fogged at this fraction of the way from fog_near to fog_far
GROUND_FOG_TOP, GROUND_FOG_RAMP = 9.0, 30.0
SKY_SPAN = 0.55            # rad above the horizon where the sky reaches sky_top
ROPE_HALF_WIDTH = 0.06     # m
HURT_ALPHA = 0x40          # 8/32, as the MCU's blend

# The MCU's HUD was laid out at 240x160; at 640x360 everything is twice the pixel size.
MCU_W = 240
PX = 2

MESSAGES = (
    "",                                          # 0
    "PRESS START",                               # 1
    "BREAK THE ARMOR",                           # 2
    "HOOK ON! (X)",                              # 3
    "STRIKE THE HEAD",                           # 4
    "HOLD ON!",                                  # 5
    "VICTORY - A TO RESTART",                    # 6 (superseded by 13)
    "DEFEATED - A TO RESTART",                   # 7 (superseded by 14)
    "CONTROLLER MISSING",                        # 8
    "CONTINUE",                                  # 9  pause menu, item selected
    "RESTART",                                   # 10
    "RECALIBRATE",                               # 11 (unused: no tilt on Alia Pad)
    "PRESS START",                               # 12 (was the tilt calibration prompt)
    "VICTORY - A TO RESTART",                    # 13
    "DEFEATED - A TO RESTART",                   # 14
    "L MOVE  R LOOK  B SHOOT  X HOOK  START MENU",  # 15
    "WAITING FOR PYTHON",                        # 16
    "BREAK THE CRYSTALS",                        # 17
    "JUMP OFF! (X)",                             # 18
    "FINISH HIM (B)",                            # 19
)
MENU_ITEMS = (9, 10)


def rgb888(c565):
    r, g, b = (c565 >> 11) & 31, (c565 >> 5) & 63, c565 & 31
    return ((r << 3 | r >> 2) << 16) | ((g << 2 | g >> 4) << 8) | (b << 3 | b >> 2)


def rgba(c565, alpha=0xFF):
    return (rgb888(c565) << 8) | alpha


def grade(c, look):
    """Mode 1 grading (art.md §4, sketch/scene.cpp grade()): RGB565 in, RGB565 out."""
    mode, sat, con, bri, gam, lift, gain = look
    if mode == 0:
        return c

    def split(v):
        return ((v >> 11) & 31) / 31.0, ((v >> 5) & 63) / 63.0, (v & 31) / 31.0

    rgb, lo, hi = split(c), split(lift), split(gain)
    y = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    exponent = 64.0 / (gam or 64)
    out = []
    for i in range(3):
        v = y + (rgb[i] - y) * sat / 128.0
        v = min(1.0, max(0.0, (v - 0.5) * con / 128.0 + 0.5 + bri / 128.0))
        out.append(min(1.0, max(0.0, lo[i] + v ** exponent * (hi[i] - lo[i]))))
    return (round(out[0] * 31) << 11) | (round(out[1] * 63) << 5) | round(out[2] * 31)


def _hash_pick(i, j):
    """Which of the two grass tones a terrain vertex gets (sketch/render.cpp bakeTerrain)."""
    h = ((i * 73856093) & 0xFFFFFFFF) ^ ((j * 19349663) & 0xFFFFFFFF)
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h >> 16) & 1


class View:
    def __init__(self, engine, scene):
        self.e = engine
        self.scene = scene
        self.meshes = self._load_meshes()
        self.rope = 0
        self.terrain = 0
        # Terrain colours are baked with their shading; the rope is a flat ribbon that never sinks into
        # the ground fog (alia-engine materials, its docs/api.md §2).
        self.ground_material = engine.create_material(ae.Material(shading=ae.Shading.UNLIT, color=ae.ColorSource.VERTEX))
        self.rope_material = engine.create_material(ae.Material(shading=ae.Shading.UNLIT, color=ae.ColorSource.VERTEX,
                                                                double_sided=True, ground_fog=False))
        self.palette = list(pal.PALETTE_565)  # graded by the current Look
        self.light = (0.0, -1.0, 0.0)
        self.set_sky(*world.blend_sky(world.TIME_OF_DAY[0], world.TIME_OF_DAY[0], 0.0))
        # What never moves lives in alia-engine's world (its docs/api.md §3): the terrain (its mesh is
        # rebuilt when the sky changes, the node stays) and the scattered rocks. Moving things are still
        # drawn per frame until the rigs move into the engine too (E4 step 4).
        engine.world.spawn(self.terrain)
        self.pool = {}       # mesh id -> nodes for this kind of object
        self.rope_node = None
        for x, z, yaw, scale, mesh_id, tint in scene.rocks:
            if mesh_id in self.meshes:
                engine.world.spawn(self.meshes[mesh_id], position=(x, world.terrain_height(scene, x, z), z), yaw=yaw,
                                   scale=scale, tint=tint)

    # ---- assets -------------------------------------------------------------------------------
    def _load_meshes(self):
        """Mesh id (gen/mesh_ids.py) -> engine mesh, from the resource pack."""
        by_name = self.e.load_meshes(str(MESH_PACK))
        return {mid: by_name[name] for mid, name in mesh_ids.NAMES.items() if name in by_name}

    def _terrain_mesh(self, grass_a, grass_b):
        s = self.scene
        n, cell, hs = s.terrain_n, s.cell, s.height_scale / 16.0
        h = s.heights

        def at(i, j):
            return h[min(max(j, 0), n - 1) * n + min(max(i, 0), n - 1)] * hs

        light = tuple(-c for c in self.light)  # towards the sun
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

    # ---- sky and Look ---------------------------------------------------------------------------
    def set_sky(self, fields, look_block):
        """world.sky_at() output: scene colours (RGB565), fog in 2 m units, sun in BAM8, and the Look."""
        look = _LOOK.unpack(look_block)
        params = look[32:39]
        self.palette = [grade(c, params) for c in look[:32]]
        self.e.set_palette(b"".join(rgb888(c).to_bytes(3, "big") for c in self.palette))
        f = self.e.frame
        f.sky_top = rgb888(grade(fields["sky_top"], params))
        f.sky_horizon = rgb888(grade(fields["sky_horizon"], params))
        f.fog_color = rgb888(grade(fields["fog_color"], params))
        f.sky_span = SKY_SPAN
        fog_near, fog_far = fields["fog_near"] * 2.0, fields["fog_far"] * 2.0
        f.fog_near, f.fog_full = fog_near, fog_near + (fog_far - fog_near) * FOG_FULL
        cam = self.e.world.camera  # the far plane is the fog's end (the MCU's far clip)
        cam.near, cam.far = NEAR_PLANE, fog_far
        f.ground_fog, f.ground_top, f.ground_ramp = look[41] / 255.0, GROUND_FOG_TOP, GROUND_FOG_RAMP
        yaw, pitch = (fields[k] * 2 * math.pi / 256 for k in ("light_yaw", "light_pitch"))
        sun = (math.cos(pitch) * math.sin(yaw), math.sin(pitch), math.cos(pitch) * math.cos(yaw))
        self.light = tuple(-c for c in sun)
        f.sun.travel, f.sun.ambient, f.sun.diffuse = self.light, SUN_AMBIENT, SUN_DIFFUSE
        self._terrain_mesh(grade(fields["grass_a"], params), grade(fields["grass_b"], params))

    # ---- one frame ------------------------------------------------------------------------------
    def update(self, frame, hand=None):
        """Every logic step: the world follows this step's Frame (alia-engine interpolates between steps);
        `hand`, the rider's hand, is where the rope starts."""
        e, f, cam = self.e, self.e.frame, frame.camera
        c = e.world.camera
        c.position, c.yaw, c.pitch, c.fov_x = (cam.x, cam.y, cam.z), cam.yaw, cam.pitch, math.radians(cam.fov)
        f.fog_steps = 0 if frame.flags & g3d.FLAG_NO_FOG else FOG_STEPS
        # Character light: from just above and right of the camera (api.md §3.3).
        fwd = (math.sin(cam.yaw) * math.cos(cam.pitch), math.sin(cam.pitch), math.cos(cam.yaw) * math.cos(cam.pitch))
        key = (-fwd[0] - 0.45 * math.cos(cam.yaw), -fwd[1] + 0.7, -fwd[2] + 0.45 * math.sin(cam.yaw))
        length = math.sqrt(sum(c * c for c in key))
        f.character.travel = tuple(-c / length for c in key)
        f.character.ambient, f.character.diffuse = CHAR_AMBIENT, CHAR_DIFFUSE
        f.overlay = rgba(pal.PALETTE_565[pal.HURT], HURT_ALPHA) if frame.flags & g3d.FLAG_HURT else 0

        self._objects(frame.objects)  # the rigs are the boss's and the player's own nodes
        self._rope(frame.hook, hand, cam)

    def draw(self, frame):
        """Every displayed frame: the HUD (the world draws itself)."""
        if not frame.flags & g3d.FLAG_NO_HUD:
            self._hud(frame.hud)

    def _objects(self, objects):
        """Bullets, sparks, the hook head, dust rings: pooled nodes by mesh. Objects have no identity from
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
        color = rgb888(self.palette[pal.ROPE]).to_bytes(3, "big") * 4
        mesh = ae.Mesh(array("f", quad).tobytes(), array("H", (0, 1, 2, 2, 1, 3)).tobytes(), vertex_rgb=color,
                       submeshes=[(0, 2, self.rope_material)])
        if self.rope:
            self.e.update_mesh(self.rope, mesh)
        else:
            self.rope = self.e.create_mesh(mesh)
            self.rope_node = self.e.world.spawn(self.rope)
        self.rope_node.visible = True

    # ---- HUD (sketch/hud.cpp, at twice the pixel size) ------------------------------------------
    def _hud(self, hud):
        w, h = self.e.scene_size
        text, shadow = rgba(pal.PALETTE_565[pal.HUD_TEXT]), rgba(pal.PALETTE_565[pal.HUD_SHADOW])

        def shade(x, y, bw, bh, alpha32):
            self.e.hud_rect(x, y, bw, bh, rgba(pal.PALETTE_565[pal.HUD_SHADOW], alpha32 * 8))

        def say(x, y, s, color=text):
            self.e.hud_text(x, y, s, color, PX, shadow)

        def centred(y, s, color=text):
            say((w - (len(s) * 6 - 1) * PX) // 2, y, s, color)

        message = MESSAGES[hud.msg] if hud.msg < len(MESSAGES) else ""
        if hud.state == g3d.STATE_FIGHT:
            for i in range(hud.hp_max):
                x, y = 8 + i * 16, 8
                if i < hud.hp:
                    self.e.hud_rect(x + PX, y + PX, 12, 12, shadow)
                    self.e.hud_rect(x, y, 12, 12, text)
                else:
                    self.e.hud_rect(x, y, 12, 12, rgba(pal.PALETTE_565[pal.HURT]))
                    self.e.hud_rect(x + PX, y + PX, 8, 8, shadow)
            if hud.boss_hp:
                bar = 260
                self.e.hud_rect((w - bar) // 2, 10, bar, 5, shadow)
                self.e.hud_rect((w - bar) // 2, 10, (bar * hud.boss_hp + 254) // 255, 5,
                                rgba(pal.PALETTE_565[pal.HUD_BAR]))
            self._reticle(hud, w // 2 + hud.reticle_dx * w / MCU_W, h // 2 + hud.reticle_dy * w / MCU_W)
            if message:
                centred(h - 45, message)
        elif hud.state == g3d.STATE_PAUSED:
            if hud.msg in MENU_ITEMS:
                bw, bh = 268, 110
                x0, y0 = (w - bw) // 2, (h - bh) // 2
                shade(x0, y0, bw, bh, 20)
                centred(y0 + 14, "PAUSED")
                for k, item in enumerate(MENU_ITEMS):
                    y = y0 + 46 + k * 26
                    color = rgba(pal.PALETTE_565[pal.HOOK_OK]) if item == hud.msg else text
                    if item == hud.msg:
                        say(x0 + 28, y, ">", color)
                    say(x0 + 54, y, MESSAGES[item], color)
            elif message:
                shade(0, h // 2 - 22, w, 44, 16)
                centred(h // 2 - 7, message)
        elif message:  # READY, WIN, LOSE
            shade(0, h - 144, w, 44, 12)
            centred(h - 129, message)

    def _reticle(self, hud, x, y):
        """Cross; corners on a part; diamond when a hook point is in range; both when both (art.md §5)."""
        x, y, p = round(x), round(y), PX
        rect = self.e.hud_rect
        if hud.reticle_flags & 2:
            col = rgba(pal.PALETTE_565[pal.HOOK_OK])
            for i in range(-4, 5):
                d = 4 - abs(i)
                rect(x + i * p, y - d * p, p, p, col)
                rect(x + i * p, y + d * p, p, p, col)
        if hud.reticle_flags & 1:
            col = rgba(pal.PALETTE_565[pal.SIGIL])
            for sx in (-1, 1):
                for sy in (-1, 1):
                    rect(x + (sx * 5 - (0 if sx < 0 else 2)) * p, y + sy * 5 * p, 3 * p, p, col)
                    rect(x + sx * 5 * p, y + (sy * 5 - (0 if sy < 0 else 2)) * p, p, 3 * p, col)
        if not hud.reticle_flags & 3:
            for o, col in ((p, rgba(pal.PALETTE_565[pal.HUD_SHADOW])), (0, rgba(pal.PALETTE_565[pal.HUD_TEXT]))):
                rect(x - 5 * p + o, y + o, 3 * p, p, col)
                rect(x + 3 * p + o, y + o, 3 * p, p, col)
                rect(x + o, y - 5 * p + o, p, 3 * p, col)
                rect(x + o, y + 3 * p + o, p, 3 * p, col)
