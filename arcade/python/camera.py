"""Third-person camera behind the PC's right shoulder: it turns with the horse (stick steering) and the right
stick adds a look offset on top; riding without looking eases it back behind the horse (tuning.py section 4)."""

import math

import screen
import tuning
import terrain

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
        self.pitch = math.radians(tuning.START_PITCH_DEG)
        self.since_look = 0.0  # s since the right stick last looked

    def turn(self, inp, dt, on_boss=False):
        """Tilt look (before the PC moves). On the boss's brow it can look further down; after letting go
        a pitch below the riding limit eases back up instead of jumping."""
        self.yaw -= inp.yaw_rate * dt  # turning right lowers yaw (see right())
        lo = math.radians(tuning.HOOKED_MIN_PITCH_DEG if on_boss else tuning.MIN_PITCH_DEG)
        hi = math.radians(tuning.MAX_PITCH_DEG)
        pitch = self.pitch + inp.pitch_rate * dt
        if pitch < lo:
            pitch = min(lo, max(pitch, self.pitch) + math.radians(tuning.MAX_PITCH_RATE_DEG) * dt)
        self.pitch = min(hi, pitch)
        self.since_look = 0.0 if inp.yaw_rate else self.since_look + dt

    def follow(self, player, dt):
        """After the PC moved: turn with its steering, and recenter behind it while it rides without tuning."""
        self.yaw += player.steer
        if tuning.RECENTER_RATE > 0 and not player.standing and self.since_look > tuning.RECENTER_DELAY_S:
            delta = (player.yaw - self.yaw + math.pi) % (2 * math.pi) - math.pi
            self.yaw += delta * min(1.0, tuning.RECENTER_RATE * dt)

    def view(self, player, scene):
        """screen.Camera looking along (yaw, pitch) from behind the PC."""
        d, r = forward(self.yaw, self.pitch), right(self.yaw)
        x = player.x - d[0] * DISTANCE + r[0] * SHOULDER
        z = player.z - d[2] * DISTANCE + r[2] * SHOULDER
        y = player.y + PIVOT_HEIGHT + LIFT - d[1] * DISTANCE
        y = max(y, terrain.terrain_height(scene, x, z) + GROUND_CLEARANCE)
        return screen.Camera(x, y, z, self.yaw, self.pitch, FOV)
