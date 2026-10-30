"""The rigs in gen/rigs.apak as alia-engine rigs, loaded once (main.py, the tools and the tests).
Bone and part meshes are found by name when a rig is spawned, so load gen/meshes.apak first to see them
(alia_view.py does)."""

from pathlib import Path

RIG_PACK = Path(__file__).resolve().parent / "gen" / "rigs.apak"
RIGS = {}  # name -> alia_engine.Rig, of the engine they were loaded into
_engine = None


def load(engine):
    """Load the rigs into `engine` (once per engine); returns them by name."""
    global _engine
    if _engine is not engine:
        RIGS.clear()
        RIGS.update(engine.load_rigs(str(RIG_PACK)))
        _engine = engine
    return RIGS
