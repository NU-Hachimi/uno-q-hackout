"""Everything the game loads into alia-engine, once per engine (main.py, the tools and the tests): the meshes
(gen/meshes.apak, by gen.mesh_ids), the rigs (gen/rigs.apak, by name; their bone and part meshes are found by
name, so the meshes come first) and the particle templates (effects.py)."""

from pathlib import Path

import effects
from gen import mesh_ids

GEN = Path(__file__).resolve().parent / "gen"
MESHES = {}     # gen.mesh_ids id -> engine mesh
RIGS = {}       # name -> alia_engine.Rig
PARTICLES = {}  # name -> alia_engine.Particles
_engine = None


def load(engine):
    """Load it all into `engine` (once per engine); returns the rigs by name."""
    global _engine
    if _engine is not engine:
        by_name = engine.load_meshes(str(GEN / "meshes.apak"))
        MESHES.clear()
        MESHES.update({mid: by_name[name] for mid, name in mesh_ids.NAMES.items() if name in by_name})
        RIGS.clear()
        RIGS.update(engine.load_rigs(str(GEN / "rigs.apak")))
        PARTICLES.clear()
        PARTICLES.update(effects.templates(engine, MESHES))
        _engine = engine
    return RIGS
