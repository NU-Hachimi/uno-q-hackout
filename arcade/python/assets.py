"""Everything the game loads into alia-engine, once per engine (main.py, the tools and the tests): the meshes
(gen/meshes.apak, by gen.mesh_ids), the rigs (gen/rigs.apak, by name; their bone and part meshes are found by
name, so the meshes come first) and the particle templates (effects.py)."""

from pathlib import Path

import effects
from gen import mesh_ids, palette

GEN = Path(__file__).resolve().parent / "gen"
MESHES = {}     # gen.mesh_ids id -> engine mesh
ROPE = 0        # the rope: a thin box 2 m long along +Z (scaled to the hook), in the graded ROPE colour
RIGS = {}       # name -> alia_engine.Rig
PARTICLES = {}  # name -> alia_engine.Particles
_engine = None


def _rope(engine):
    """A thin box from z -1 to 1, unlit in the palette's ROPE colour (graded with the rest), never in the ground fog."""
    import alia_engine as ae
    from array import array
    w = 0.06
    p = [-w, -w, -1, w, -w, -1, w, w, -1, -w, w, -1, -w, -w, 1, w, -w, 1, w, w, 1, -w, w, 1]
    i = [0, 3, 2, 0, 2, 1, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 2, 3, 7, 2, 7, 6, 1, 2, 6, 1, 6, 5, 0, 4, 7, 0, 7, 3]
    material = engine.create_material(ae.Material(shading=ae.Shading.UNLIT, palette_index=palette.ROPE,
                                                  double_sided=True, ground_fog=False))
    return engine.create_mesh(ae.Mesh(array("f", p).tobytes(), array("H", i).tobytes(), submeshes=[(0, 12, material)]))


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
        global ROPE
        ROPE = _rope(engine)
        _engine = engine
    return RIGS
