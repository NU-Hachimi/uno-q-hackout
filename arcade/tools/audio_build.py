#!/usr/bin/env python3
"""Render assets/audio/*.mid into python/music/*.wav, which python/audio.py plays on the board.

    python3 tools/audio_build.py [--sf2 PATH]   (run from arcade/; needs fluidsynth)

Every track in assets/audio/music.json is rendered with the board's own General MIDI soundfont
(TimGM6mb), downmixed to 22.05 kHz mono 16-bit and cut to its `end`. A loop (with `loop_start`) gets
its release tail mixed back in at `loop_start`, so looping end -> loop_start is seamless; a one-shot
keeps up to TAIL seconds of its tail. The WAVs are committed, so the game never needs fluidsynth.
"""

import argparse
import array
import json
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "audio"
OUT = ROOT / "python" / "music"
RATE = 22050
GAIN = 0.6        # fluidsynth master gain; the battle theme peaks around 0.8 full scale
TAIL = 3.0        # s of release kept after a one-shot's end
ONE_SHOT_PEAK = 0.7  # one-shots are normalised to this, so a soft jingle is still heard over the room
SOUNDFONTS = (ROOT / "tool" / "sf2" / "TimGM6mb.sf2", Path("/usr/share/sounds/sf2/TimGM6mb.sf2"))


def fail(message):
    sys.exit(f"audio_build: {message}")


def render(mid, sf2):
    """fluidsynth -> mono samples (array of int16) at RATE."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "out.wav"
        subprocess.run(["fluidsynth", "-ni", "-q", "-g", str(GAIN), "-r", str(RATE), "-F", str(wav), str(sf2),
                        str(mid)], check=True, stderr=subprocess.DEVNULL)  # it probes ALSA even for a file
        with wave.open(str(wav)) as w:
            if w.getsampwidth() != 2 or w.getframerate() != RATE:
                fail(f"{mid.name}: fluidsynth wrote {w.getsampwidth() * 8}-bit {w.getframerate()} Hz")
            frames = array.array("h", w.readframes(w.getnframes()))
            channels = w.getnchannels()
    if channels == 1:
        return frames
    return array.array("h", ((frames[i] + frames[i + 1]) // 2 for i in range(0, len(frames), 2)))


def shape(samples, track):
    end = int(track["end"] * RATE)
    if "loop_start" not in track:
        out = samples[:end + int(TAIL * RATE)]
        scale = ONE_SHOT_PEAK * 32767 / max(1, max(abs(s) for s in out))
        return array.array("h", (max(-32768, min(32767, round(s * scale))) for s in out))
    start = int(track["loop_start"] * RATE)
    body = samples[:end]
    for i, s in enumerate(samples[end:]):  # the tail rings on into the next loop
        if start + i >= end:
            break
        body[start + i] = max(-32768, min(32767, body[start + i] + s))
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sf2", type=Path, help="General MIDI soundfont (default: TimGM6mb, as on the board)")
    args = parser.parse_args()
    if not shutil.which("fluidsynth"):
        fail("needs fluidsynth on PATH")
    sf2 = args.sf2 or next((p for p in SOUNDFONTS if p.exists()), None)
    if not sf2 or not sf2.exists():
        fail("no soundfont: copy /usr/share/sounds/sf2/TimGM6mb.sf2 from the board into tool/sf2/ or pass --sf2")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, track in json.loads((ASSETS / "music.json").read_text()).items():
        samples = shape(render(ASSETS / f"{name}.mid", sf2), track)
        with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(samples.tobytes())
        peak = max(abs(s) for s in samples) / 32768
        print(f"wrote: python/music/{name}.wav  {len(samples) / RATE:.1f} s, peak {peak:.2f}")
    (OUT / "music.json").write_text((ASSETS / "music.json").read_text())


if __name__ == "__main__":
    main()
