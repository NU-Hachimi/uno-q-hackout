import json
import math
from pathlib import Path

import rig
from gen.rigs import RIGS

MOOSE = RIGS[1]
GOLDEN = json.loads((Path(__file__).parent / "golden" / "rig_moose.json").read_text())


def test_golden_matches_rig_py():
    # The golden file is written by tools/rig_build.py from rig.py; this guards against drift.
    for anim in GOLDEN["anims"]:
        for phase, want in zip(GOLDEN["phases"], anim["poses"]):
            poses = rig.pose(MOOSE, anim["id"], phase)
            origin = rig.transform(poses[0], (0, 0, 0))
            assert all(abs(a - b) < 1e-4 for a, b in zip(origin, want[0][:3]))


def test_key_positions():
    loop = {"keys": 4, "loop": True}
    assert rig.key_position(loop, 0) == (0, 1, 0.0)
    i, j, t = rig.key_position(loop, 224)  # f = 3.5: last key blends back to the first
    assert (i, j) == (3, 0) and abs(t - 0.5) < 1e-9
    once = {"keys": 5, "loop": False}
    assert rig.key_position(once, 0) == (0, 1, 0.0)
    assert rig.key_position(once, 255) == (3, 4, 1.0)


def test_rest_pose_and_kneel():
    standing = rig.pose(MOOSE, 0, 0)
    assert abs(rig.transform(standing[0], (0, 0, 0))[1] - 6.0) < 1e-9  # torso 6 m up
    kneeling = rig.pose(MOOSE, 6, 255)
    assert abs(rig.transform(kneeling[0], (0, 0, 0))[1] - 3.7) < 1e-9  # root_y -2.3


def test_world_transform_and_inverse():
    poses = rig.world_poses(MOOSE, 0, 0, 10.0, 1.0, -5.0, math.pi / 2)
    root = rig.transform(poses[0], (0, 0, 0))
    assert all(abs(a - b) < 1e-9 for a, b in zip(root, (10.0, 7.0, -5.0)))
    # Yaw pi/2 turns the rig's +Z (its front) towards +X.
    nose = rig.transform_dir(poses[0], (0, 0, 1))
    assert abs(nose[0] - 1) < 1e-9
    back = rig.transform(rig.inverse(poses[2]), rig.transform(poses[2], (0.3, -0.2, 1.1)))
    assert all(abs(a - b) < 1e-9 for a, b in zip(back, (0.3, -0.2, 1.1)))


def test_slot_matrix_uses_bone_offset_and_rotation():
    poses = rig.pose(MOOSE, 0, 0)
    back = rig.slot_matrix(MOOSE, poses, 4)  # root, offset (0, 1.6, -1.5), rot (-90, 0, 0)
    assert all(abs(a - b) < 1e-9 for a, b in zip(rig.transform(back, (0, 0, 0)), (0, 7.6, -1.5)))
    up = rig.transform_dir(back, (0, 0, 1))  # part meshes face +Z; rx -90 turns that up
    assert abs(up[1] - 1) < 1e-9
