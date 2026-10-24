"""g3d protocol (docs/api.md §2–§4): pure packing helpers plus a small Bridge client.

Packing functions have no board dependencies so desktop tests can import them.
Units: metres and radians in, i16 1/64 m and BAM angles on the wire.
"""

import math
import struct
from dataclasses import dataclass, field

G3D_VERSION = 1
MAX_PAYLOAD = 192
MAX_OBJ = 12
CHUNK_SIZE = 192

KIND_TERRAIN = 1
KIND_ROCKS = 2
KIND_LOOK = 3

# Frame header game_state values.
STATE_READY, STATE_FIGHT, STATE_WIN, STATE_LOSE, STATE_PAUSED = range(5)

# Input buttons: bits 0-3 are held now, bits 4-7 were pressed at least once since the last
# reply (latched by the MCU so taps shorter than a frame are not lost).
BTN_A, BTN_B, BTN_C, BTN_STICK = 1, 2, 4, 8

FLAG_WIREFRAME, FLAG_NO_FOG, FLAG_NO_HUD, FLAG_HURT, FLAG_FREEZE, FLAG_NO_GRADE = (1 << i for i in range(6))

_HEADER = struct.Struct("<BBBBhhhHhBBBBBBbbBB")   # 24 B, §3.3
_RIG = struct.Struct("<BBBBhhhHI")                # 16 B
_HOOK = struct.Struct("<BBhhh")                   # 8 B
_OBJ = struct.Struct("<BBhhhHbB")                 # 12 B
_INPUT = struct.Struct("<BBBBbbhhhbbBB")          # 16 B, §3.5
_SCENE = struct.Struct("<BBHHHBBBBhhBBHHBBB")     # 25 B before slot_variant[], §3.1
_CAPS = struct.Struct("<BHHBBBBBB")               # §3.4
_ROCK = struct.Struct("<hhBBBB")                  # 8 B
assert (_HEADER.size, _RIG.size, _HOOK.size, _OBJ.size, _INPUT.size, _SCENE.size) == (24, 16, 8, 12, 16, 25)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def pos16(metres):
    return _clamp(round(metres * 64), -32768, 32767)


def bam16(radians):
    return round(radians / (2 * math.pi) * 65536) & 0xFFFF


def bam16s(radians):
    v = bam16(radians)
    return v - 65536 if v >= 32768 else v


def bam8s(radians):
    v = round(radians / (2 * math.pi) * 256) & 0xFF
    return v - 256 if v >= 128 else v


def u8(v):
    return _clamp(int(v), 0, 255)


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF)."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass
class Camera:
    x: float
    y: float
    z: float
    yaw: float = 0.0     # rad; 0 faces +Z
    pitch: float = 0.0   # rad; positive looks up
    fov: float = 75.0    # horizontal, degrees


@dataclass
class Obj:
    """One drawn object. The MCU builds T(pos) · Ry(yaw) · Rx(pitch) · S(scale), so a positive
    pitch tips the mesh's +Z nose downwards."""
    mesh: int
    x: float
    y: float
    z: float
    yaw: float = 0.0
    pitch: float = 0.0
    scale: float = 1.0
    tint: int = 0        # palette index; 0 keeps the mesh colours


@dataclass
class Hud:
    state: int = STATE_READY
    hp: int = 0
    hp_max: int = 0
    boss_hp: int = 0
    msg: int = 0
    reticle_dx: int = 0  # pixels at 240x160, sent in 2 px units
    reticle_dy: int = 0
    reticle_flags: int = 0
    timer: int = 0


@dataclass
class Rig:
    rig_id: int = 0
    anim: int = 0
    phase: int = 0
    hit_slot: int = 0xFF
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    part_alive: int = 0


@dataclass
class Hook:
    flags: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


def pack_frame(seq, cam, objs, hud, rig=None, hook=None, flags=0):
    objs = list(objs)[:MAX_OBJ]
    rig = rig or Rig()
    hook = hook or Hook()
    out = bytearray(_HEADER.pack(
        G3D_VERSION, seq & 0xFF, flags & 0xFF, len(objs),
        pos16(cam.x), pos16(cam.y), pos16(cam.z), bam16(cam.yaw), bam16s(cam.pitch), u8(round(cam.fov)),
        u8(hud.state), u8(hud.hp), u8(min(hud.hp_max, 10)), u8(hud.boss_hp), u8(hud.msg),
        _clamp(round(hud.reticle_dx / 2), -128, 127), _clamp(round(hud.reticle_dy / 2), -128, 127),
        u8(hud.reticle_flags), u8(hud.timer)))
    out += _RIG.pack(u8(rig.rig_id), u8(rig.anim), u8(rig.phase), u8(rig.hit_slot),
                     pos16(rig.x), pos16(rig.y), pos16(rig.z), bam16(rig.yaw), rig.part_alive & 0xFFFFFFFF)
    out += _HOOK.pack(u8(hook.flags), 0, pos16(hook.x), pos16(hook.y), pos16(hook.z))
    for o in objs:
        out += _OBJ.pack(u8(o.mesh), u8(o.tint), pos16(o.x), pos16(o.y), pos16(o.z),
                         bam16(o.yaw), bam8s(o.pitch), _clamp(round(o.scale * 16), 1, 255))
    assert len(out) == 48 + 12 * len(objs) <= MAX_PAYLOAD
    return bytes(out)


@dataclass
class RawInput:
    seq_ack: int
    connected: int   # bit0 Buttons, bit1 Joystick, bit2 Movement
    held: int        # BTN_* bits held right now
    pressed: int     # BTN_* bits pressed since the previous reply
    jx: int
    jy: int
    ax: int          # mg, raw, includes gravity
    ay: int
    az: int
    gx: int          # deg/s / 4 (optional, may be 0)
    gy: int
    render_ms: int
    push_ms: int


def unpack_input(data):
    """Input from g3d_frame: 16 raw bytes, or 32 hex chars when the MCU cannot return bin."""
    if isinstance(data, str):
        try:
            data = bytes.fromhex(data)
        except ValueError:
            return None
    if not data or len(data) != _INPUT.size:
        return None
    ver, seq, conn, buttons, jx, jy, ax, ay, az, gx, gy, rms, pms = _INPUT.unpack(data)
    if ver != G3D_VERSION:
        return None
    return RawInput(seq, conn, buttons & 0x0F, buttons >> 4, jx, jy, ax, ay, az, gx, gy, rms, pms)


@dataclass
class SceneDef:
    heights: list            # terrain_n² ints in -127..127, row-major (z rows, x columns)
    terrain_n: int = 17
    cell: float = 16.0       # m
    origin_x: float = -128.0  # m, corner of vertex (0, 0)
    origin_z: float = -128.0
    height_scale: int = 1    # 1/16 m per height unit
    sky_top: int = 0
    sky_horizon: int = 0
    fog_color: int = 0
    fog_near: float = 40.0   # m
    fog_far: float = 120.0   # m, also the far clip plane
    grass_a: int = 0
    grass_b: int = 0
    light_yaw: int = 0       # BAM8
    light_pitch: int = 0     # BAM8
    rig_id: int = 0
    slot_variants: list = field(default_factory=list)
    rocks: list = field(default_factory=list)  # (x, z, yaw_rad, scale, variant, tint)
    look: bytes = b""        # 76 B Look block, or empty for the MCU default


def pack_scene(scene):
    """Return (header, [(kind, index, data)], crc16) for g3d_scene_begin/chunk/commit."""
    n = scene.terrain_n
    if not 2 <= n <= 33 or len(scene.heights) != n * n:
        raise ValueError("terrain must be n x n with 2 <= n <= 33")
    if len(scene.rocks) > 64 or len(scene.slot_variants) > 32:
        raise ValueError("too many rocks or slots")
    header = _SCENE.pack(
        G3D_VERSION, u8(scene.rig_id), scene.sky_top, scene.sky_horizon, scene.fog_color,
        u8(round(scene.fog_near / 2)), u8(round(scene.fog_far / 2)), n, u8(round(scene.cell)),
        pos16(scene.origin_x), pos16(scene.origin_z), u8(scene.height_scale), len(scene.rocks),
        scene.grass_a, scene.grass_b, u8(scene.light_yaw), u8(scene.light_pitch), len(scene.slot_variants))
    header += bytes(u8(v) for v in scene.slot_variants)
    chunks = []
    terrain = bytes(_clamp(int(h), -127, 127) & 0xFF for h in scene.heights)
    for index, start in enumerate(range(0, len(terrain), CHUNK_SIZE)):
        chunks.append((KIND_TERRAIN, index, terrain[start:start + CHUNK_SIZE]))
    rocks = [_ROCK.pack(pos16(x), pos16(z), bam16(yaw) >> 8, _clamp(round(s * 16), 1, 255), u8(v), u8(t))
             for x, z, yaw, s, v, t in scene.rocks]
    for index in range(0, len(rocks), 24):
        chunks.append((KIND_ROCKS, index // 24, b"".join(rocks[index:index + 24])))
    if scene.look:
        if len(scene.look) != 76:
            raise ValueError("Look block must be 76 bytes")
        chunks.append((KIND_LOOK, 0, bytes(scene.look)))
    crc = 0xFFFF
    for _, _, data in chunks:  # already in kind, then index order
        crc = crc16(data, crc)
    return header, chunks, crc


def unpack_caps(data):
    if isinstance(data, str):
        data = bytes.fromhex(data) if data else b""
    if not data or len(data) < _CAPS.size:
        return None
    ver, w, h, tile_h, max_obj, max_slots, n_mesh, n_rig, flags = _CAPS.unpack(data[:_CAPS.size])
    return {"ver": ver, "render_w": w, "render_h": h, "tile_h": tile_h, "max_obj": max_obj,
            "max_slots": max_slots, "n_mesh": n_mesh, "n_rig": n_rig, "bin_return": bool(flags & 1),
            "pixel_grade": bool(flags & 2)}


class G3D:
    """Bridge client. `call` is Bridge.call (method, *params, timeout=seconds)."""

    def __init__(self, call, timeout=0.5):
        self.call = call
        self.timeout = timeout
        self.failures = 0

    def hello(self):
        caps = unpack_caps(self.call("g3d_hello", G3D_VERSION, timeout=2))
        if not caps:
            raise RuntimeError("MCU does not speak g3d v%d; flash the matching sketch" % G3D_VERSION)
        return caps

    def load_scene(self, scene, retries=3):
        header, chunks, crc = pack_scene(scene)
        for _ in range(retries):
            if not self.call("g3d_scene_begin", header, timeout=2):
                continue
            if all(self.call("g3d_scene_chunk", k, i, d, timeout=2) for k, i, d in chunks) and \
                    self.call("g3d_scene_commit", crc, timeout=2):
                return
        raise RuntimeError("scene upload failed %d times" % retries)

    def frame(self, packet):
        """Send one frame; returns RawInput, or None when the call failed or was rejected."""
        try:
            raw = unpack_input(self.call("g3d_frame", packet, timeout=self.timeout))
        except Exception:
            raw = None
        self.failures = 0 if raw else self.failures + 1
        return raw

    def release(self):
        try:
            self.call("g3d_release", timeout=1)
        except Exception:
            pass
