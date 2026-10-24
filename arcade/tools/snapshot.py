#!/usr/bin/env python3
"""Drive the real Python game with scripted inputs and save the scene upload plus a few frames,
so tests/cpp/render_preview.sh --snapshots can render them with the MCU renderer.

    python3 tools/snapshot.py OUT_DIR
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import g3d  # noqa: E402
import world  # noqa: E402
from game import Game  # noqa: E402

DT = 0.05
NEUTRAL_G = (0, 0, 1000)  # mg; any pose works, the game calibrates on the A press


def raw(jx=0, jy=0, held=0, pressed=0, connected=7, accel=NEUTRAL_G):
    # Stick values in raw units with preview.py's INVERT_Y: pushing forward reads positive jy.
    return g3d.RawInput(0, connected, held, pressed, jx, jy, *accel, 0, 0, 0, 0)


def write_scene(path, scene):
    header, chunks, crc = g3d.pack_scene(scene)
    out = struct.pack("<H", len(header)) + header + bytes([len(chunks)])
    for kind, index, data in chunks:
        out += struct.pack("<BBH", kind, index, len(data)) + data
    path.write_bytes(out + struct.pack("<H", crc))


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    scene = world.make_scene(seed=1)
    write_scene(out / "scene.bin", scene)
    game = Game(scene)
    seq = 0

    def run(name, inputs):
        nonlocal seq
        frame = None
        for r in inputs:
            frame = game.step(r, DT)
        cam, objs, hud, flags = frame
        (out / f"{name}.frame").write_bytes(g3d.pack_frame(seq, cam, objs, hud, flags=flags))
        seq += 1

    run("1_ready", [raw()])
    run("2_fight_hint", [raw(pressed=g3d.BTN_A, held=g3d.BTN_A), raw()])
    # Walk forward and right for 1.5 s, then hold B while turning a little with tilt.
    walk = [raw(jx=40, jy=110)] * 30
    tilt_right = (300, 0, 950)
    shoot = [raw(held=g3d.BTN_B, accel=tilt_right)] * 6
    run("3_walk_shoot", walk + shoot)
    run("4_menu", [raw(pressed=g3d.BTN_A, held=g3d.BTN_A), raw(jy=-110)])
    run("5_missing", [raw(connected=5)])
    print(f"wrote {out}/scene.bin and {seq} frames")


if __name__ == "__main__":
    main()
