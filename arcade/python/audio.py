"""Megalith's music on alia-engine's mixer (its docs/api.md §6): the engine mixes and hands the system one
48 kHz stream; this only says which track, how loud, and where each loops.

Tracks are python/music/*.wav (tools/audio_build.py); music.json says which ones loop and from where, and
where each ends. Call play(name, volume) every step: the same track only changes its volume, another one
crossfades over FADE, a finished one-shot (a jingle) stays quiet while it is still the one asked for.
"""

import json
from pathlib import Path

FADE = 0.4                # s across a change of track or volume
MASTER = 0.8              # overall music level; the system volume stays as the board has it
FOLDER = Path(__file__).resolve().parent / "music"


class Music:
    def __init__(self, engine, folder=FOLDER):
        self.audio = engine.audio
        folder = Path(folder)
        self.table = json.loads((folder / "music.json").read_text()) if (folder / "music.json").exists() else {}
        self.sounds = {name: self.audio.load(str(folder / f"{name}.wav")) for name in self.table
                       if (folder / f"{name}.wav").exists()}
        if not self.sounds:
            print("music: no tracks, playing nothing")

    def play(self, name, volume=1.0):
        """Wanted track (None for silence) and its level 0..1."""
        sound = self.sounds.get(name)
        if sound is None:
            self.audio.play_music(None, fade=FADE)
            return
        track = self.table[name]
        self.audio.play_music(sound, volume=max(0.0, min(1.0, volume)) * MASTER, loop="loop_start" in track,
                              loop_start=track.get("loop_start", 0.0), end=track.get("end", 0.0), fade=FADE)

    def close(self):
        self.audio.play_music(None, fade=0)
