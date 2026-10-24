import math
import struct

import pytest

import g3d


def test_crc16_check_value():
    assert g3d.crc16(b"123456789") == 0x29B1  # CRC-16/CCITT-FALSE reference


def test_frame_length_and_header():
    objs = [g3d.Obj(0, 1.0, 2.0, -3.0, yaw=math.pi / 2, scale=1.0, tint=13), g3d.Obj(1, 0, 0, 0)]
    pkt = g3d.pack_frame(300, g3d.Camera(1.5, 2.0, -4.0, yaw=math.pi, pitch=-0.25, fov=75),
                         objs, g3d.Hud(state=g3d.STATE_FIGHT, hp=4, hp_max=5, msg=9, reticle_dx=-10))
    assert len(pkt) == g3d.FRAME_HEADER + 12 * 2 == 83 + 24
    ver, seq, flags, n_obj, cx, cy, cz, yaw, pitch, fov, state, hp, hp_max, boss, msg, rdx, rdy, rfl, timer = \
        struct.unpack_from("<BBBBhhhHhBBBBBBbbBB", pkt)
    assert (ver, seq, n_obj, cx, cy, cz, yaw, fov) == (2, 300 & 0xFF, 2, 96, 128, -256, 32768, 75)
    assert pitch == round(-0.25 / (2 * math.pi) * 65536)
    assert (state, hp, hp_max, msg, rdx) == (1, 4, 5, 9, -5)
    mesh, tint, x, y, z, oyaw, opitch, scale = struct.unpack_from("<BBhhhHbB", pkt, 83)
    assert (mesh, tint, x, y, z, oyaw, scale) == (0, 13, 64, 128, -192, 16384, 16)
    assert all(pkt[24 + 17 * k] == 0 for k in range(3))  # no rigs: every block has rig_id 0


def test_frame_clamps_and_limits():
    objs = [g3d.Obj(1, 9999, -9999, 0, scale=100)] * 20
    pkt = g3d.pack_frame(0, g3d.Camera(0, 0, 0), objs, g3d.Hud(hp_max=50, reticle_dx=1000))
    assert len(pkt) == 83 + 12 * g3d.MAX_OBJ <= g3d.MAX_PAYLOAD
    assert struct.unpack_from("<B", pkt, 17)[0] == 10
    assert struct.unpack_from("<b", pkt, 20)[0] == 127
    _, _, x, y, _, _, _, scale = struct.unpack_from("<BBhhhHbB", pkt, 83)
    assert (x, y, scale) == (32767, -32768, 255)


def test_input_bin_and_hex():
    raw = struct.pack("<BBBBbbhhhbbBB", 2, 7, 7, 0x31, -20, 100, 50, -75, 1000, 0, 0, 40, 30)
    for data in (raw, raw.hex()):
        inp = g3d.unpack_input(data)
        assert (inp.seq_ack, inp.held, inp.pressed, inp.jx, inp.az, inp.render_ms) == (7, 0x1, 0x3, -20, 1000, 40)
    assert g3d.unpack_input(b"") is None
    assert g3d.unpack_input(raw[:-1]) is None
    assert g3d.unpack_input("zz") is None
    assert g3d.unpack_input(b"\x01" + raw[1:]) is None  # v1 Input


def test_scene_chunks_and_crc():
    n = 17
    scene = g3d.SceneDef(heights=[(i % 255) - 127 for i in range(n * n)], terrain_n=n,
                         rocks=[(1.0, 2.0, 0.5, 1.5, 0, 0)] * 30)
    header, chunks, crc = g3d.pack_scene(scene)
    assert len(header) == 25
    terrain = [c for c in chunks if c[0] == g3d.KIND_TERRAIN]
    assert [i for _, i, _ in terrain] == [0, 1] and sum(len(d) for _, _, d in terrain) == n * n
    rocks = [c for c in chunks if c[0] == g3d.KIND_ROCKS]
    assert [len(d) for _, _, d in rocks] == [24 * 8, 6 * 8]
    assert crc == g3d.crc16(b"".join(d for _, _, d in chunks))
    assert all(len(d) <= g3d.CHUNK_SIZE for _, _, d in chunks)


def test_scene_rejects_bad_terrain():
    with pytest.raises(ValueError):
        g3d.pack_scene(g3d.SceneDef(heights=[0] * 10, terrain_n=17))


def test_rig_blocks():
    rigs = [g3d.Rig(1, 2, 128, 3, 1.0, 0.5, -2.0, math.pi, 0xFF),
            None,
            g3d.Rig(4, 1, 7, x=0.25, char_light=True, fade=0.5)]
    pkt = g3d.pack_frame(0, g3d.Camera(0, 0, 0), [], g3d.Hud(), rigs=rigs)
    assert len(pkt) == 83
    rid, anim, phase, hit, x, y, z, yaw, alive, rflags = struct.unpack_from("<BBBBhhhHIB", pkt, 24)
    assert (rid, anim, phase, hit, x, y, z, yaw, alive, rflags) == (1, 2, 128, 3, 64, 32, -128, 32768, 0xFF, 0)
    assert pkt[24 + 17] == 0  # empty block 1
    rid, _, _, _, x, _, _, _, _, rflags = struct.unpack_from("<BBBBhhhHIB", pkt, 24 + 34)
    assert (rid, x, rflags & 1, rflags >> 1) == (4, 16, 1, 64)
