"""Third-person camera: tilt turns the view, the camera sits behind the PC's right shoulder."""

import math

import g3d
import tilt_config as tilt
import world

DISTANCE = 6.0             # m behind the pivot
PIVOT_HEIGHT = 1.6         # m above the PC's feet
LIFT = 0.9                 # m above the orbit, so the PC sits below the reticle
SHOULDER = 0.7             # m to the right, so the PC does not hide the reticle
GROUND_CLEARANCE = 0.4
FOV = 75


def forward(yaw, pitch=0.0):
    """Unit view direction; yaw 0 faces +Z, positive pitch looks up."""
    return (math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch))


def right(yaw):
    """Screen-right on the ground plane. With +Y up and the view along +Z, +X is on the left."""
    return (-math.cos(yaw), 0.0, math.sin(yaw))


class ThirdPersonCamera:
    def __init__(self, yaw=0.0):
        self.yaw = yaw
        self.pitch = math.radians(tilt.START_PITCH_DEG)

    def turn(self, inp, dt):
        self.yaw -= inp.yaw_rate * dt  # turning right lowers yaw (see right())
        lo, hi = math.radians(tilt.MIN_PITCH_DEG), math.radians(tilt.MAX_PITCH_DEG)
        self.pitch = min(hi, max(lo, self.pitch + inp.pitch_rate * dt))

    def view(self, player, scene):
        """g3d.Camera looking along (yaw, pitch) from behind the PC."""
        d, r = forward(self.yaw, self.pitch), right(self.yaw)
        x = player.x - d[0] * DISTANCE + r[0] * SHOULDER
        z = player.z - d[2] * DISTANCE + r[2] * SHOULDER
        y = player.y + PIVOT_HEIGHT + LIFT - d[1] * DISTANCE
        y = max(y, world.terrain_height(scene, x, z) + GROUND_CLEARANCE)
        return g3d.Camera(x, y, z, self.yaw, self.pitch, FOV)
