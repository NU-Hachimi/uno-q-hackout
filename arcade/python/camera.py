"""Third-person camera behind the PC's right shoulder: it turns with the horse (stick steering) and tilt adds
a look offset on top; riding without tilt eases it back behind the horse (tilt_config.py section 6)."""

import math

import g3d
import tilt_config as tilt
import world

DISTANCE = 7.5             # m behind the pivot (the PC rides a horse: 2.7 m tall, 2.4 m long)
PIVOT_HEIGHT = 2.2         # m above the horse's hooves
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
        self.since_tilt = 0.0  # s since the last tilt look input

    def turn(self, inp, dt):
        """Tilt look (before the PC moves)."""
        self.yaw -= inp.yaw_rate * dt  # turning right lowers yaw (see right())
        lo, hi = math.radians(tilt.MIN_PITCH_DEG), math.radians(tilt.MAX_PITCH_DEG)
        self.pitch = min(hi, max(lo, self.pitch + inp.pitch_rate * dt))
        self.since_tilt = 0.0 if inp.yaw_rate else self.since_tilt + dt

    def follow(self, player, dt):
        """After the PC moved: turn with its steering, and recenter behind it while it rides without tilt."""
        self.yaw += player.steer
        if tilt.RECENTER_RATE > 0 and not player.standing and self.since_tilt > tilt.RECENTER_DELAY_S:
            delta = (player.yaw - self.yaw + math.pi) % (2 * math.pi) - math.pi
            self.yaw += delta * min(1.0, tilt.RECENTER_RATE * dt)

    def view(self, player, scene):
        """g3d.Camera looking along (yaw, pitch) from behind the PC."""
        d, r = forward(self.yaw, self.pitch), right(self.yaw)
        x = player.x - d[0] * DISTANCE + r[0] * SHOULDER
        z = player.z - d[2] * DISTANCE + r[2] * SHOULDER
        y = player.y + PIVOT_HEIGHT + LIFT - d[1] * DISTANCE
        y = max(y, world.terrain_height(scene, x, z) + GROUND_CLEARANCE)
        return g3d.Camera(x, y, z, self.yaw, self.pitch, FOV)
