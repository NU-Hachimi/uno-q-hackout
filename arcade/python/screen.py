"""What the game shows each step (game.Game.step -> Frame), read by view.py: the camera, the objects
that come and go (bullets, the hook head, dust rings, the finisher's flash), the HUD, the rope's hook,
and the rig blocks (the rigs themselves are the boss's and the player's own nodes in the engine's world;
the blocks remain for the snapshots' state dumps). These were the MCU protocol's records (the old g3d.py);
the wire format is gone with the MCU, the plain data stays."""

from dataclasses import dataclass

# Hud.state
STATE_READY, STATE_FIGHT, STATE_WIN, STATE_LOSE, STATE_PAUSED = range(5)

# Frame.flags
FLAG_NO_FOG, FLAG_NO_HUD, FLAG_HURT = 2, 4, 8


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
    """One object drawn this step: T(pos) · Ry(yaw) · Rx(pitch) · S(scale), so a positive pitch tips the mesh's
    +Z nose downwards."""
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
    reticle_dx: int = 0  # pixels at 240x160 (hud.py scales them)
    reticle_dy: int = 0
    reticle_flags: int = 0
    timer: int = 0


@dataclass
class Rig:
    """One rig's placement and pose. (x, y, z, yaw) places the rig origin; the root bone's offset sits on top of it."""
    rig_id: int = 0          # 0: none
    anim: int = 0
    phase: int = 0
    hit_slot: int = 0xFF
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    part_alive: int = 0
    char_light: bool = False  # camera-relative key light instead of the sun
    fade: float = 0.0         # 0..1: blend towards the fog colour; 1 is not drawn


@dataclass
class Hook:
    flags: int = 0           # bit0: the rope is out, bit1: hooked on
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class Frame:
    """One step's picture."""
    camera: Camera
    objects: list
    hud: Hud
    rigs: list           # boss, horse, rider
    hook: Hook
    flags: int = 0
