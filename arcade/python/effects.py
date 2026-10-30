"""Purely visual effects as alia-engine particle templates (its docs/api.md §6): nothing the gameplay reads
back. The numbers are the ones player.py and finisher.py used when they simulated these in Python (and the
MCU's MAX_SPARKS = 4 limit is gone). The dust rings and the tracers stay gameplay objects: they hurt or hit."""

from gen import mesh_ids, palette


def templates(engine, meshes):
    """name -> alia_engine.Particles; `meshes` maps gen.mesh_ids to engine meshes (assets.load)."""
    spark = meshes.get(mesh_ids.SPARK, 0)
    return {
        # A shot landing: one spark that grows to 4x and spins, gone in 0.25 s; the burst gives its colour.
        "hit": engine.particles(spark, lifetime=0.25, size=1.0, size_over_life=[(0, 1), (1, 4)], spin=20.0,
                                max_particles=32),
        # A part breaking: fragments thrown out (2-5 m/s) and up, falling, growing to 2x; the part's colour.
        "debris": engine.particles(spark, lifetime=0.6, speed=(2.0, 5.0), velocity=(0, 4.0, 0), size=3.0,
                                   size_over_life=[(0, 1), (1, 2)], spin=20.0, gravity=1.0, shape="ring",
                                   max_particles=64),
        # The finisher: sparks off the hand that shrink as they fall. Game time: finisher.py sets the
        # emitter's time_scale to its slow motion and hit stop.
        "orbs": engine.particles(spark, lifetime=0.8, speed=(2.5, 5.0), velocity=(0, 3.0, 0), size=1.2,
                                 size_over_life=[(0, 1), (1, 0.3)], spin=20.0, gravity=1.0, shape="ring",
                                 tint=palette.SIGIL, max_particles=64),
    }
