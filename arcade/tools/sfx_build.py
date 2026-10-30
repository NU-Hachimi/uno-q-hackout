#!/usr/bin/env python3
"""Synthesize Megalith's sound effects into python/sfx/*.wav (16-bit PCM, 22 kHz mono), played through
alia-engine's mixer (python/sfx.py). Made in code, no recordings: noise bursts, swept sines and decays,
in keeping with the low-poly look. Deterministic, so the files only change when this does.

    python3 tools/sfx_build.py          (rewrites python/sfx/)
    python3 tools/sfx_build.py --check  (exit 1 if they are stale)
"""

import argparse
import array
import io
import math
import random
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "python" / "sfx"
RATE = 22050


def frames(seconds):
    return range(int(seconds * RATE))


def env(t, attack, decay):
    """Linear attack, exponential decay (decay: seconds to fall to about 5%)."""
    return min(1.0, t / attack) * math.exp(-3.0 * max(0.0, t - attack) / decay) if attack > 0 else math.exp(-3.0 * t / decay)


def lowpass(samples, cutoff):
    """One-pole low-pass, cutoff in Hz."""
    k = 1 - math.exp(-2 * math.pi * cutoff / RATE)
    y, out = 0.0, []
    for x in samples:
        y += k * (x - y)
        out.append(y)
    return out


def sweep(f0, f1, seconds, shape=math.sin):
    """A tone gliding from f0 to f1 Hz (exponentially) over `seconds`, its phase kept continuous."""
    phase, out = 0.0, []
    n = int(seconds * RATE)
    for i in range(n):
        f = f0 * (f1 / f0) ** (i / max(1, n - 1))
        phase += 2 * math.pi * f / RATE
        out.append(shape(phase))
    return out


def square(phase):
    return 1.0 if math.sin(phase) >= 0 else -1.0


def mix(*parts):
    n = max(len(p) for p in parts)
    return [sum(p[i] for p in parts if i < len(p)) for i in range(n)]


def shot(rng):
    """A dry crack: a noise burst over a falling thump."""
    noise = lowpass([rng.uniform(-1, 1) for _ in frames(0.12)], 5000)
    crack = [x * env(i / RATE, 0.001, 0.04) for i, x in enumerate(noise)]
    thump = [x * 0.6 * env(i / RATE, 0.002, 0.08) for i, x in enumerate(sweep(140, 55, 0.15))]
    return mix(crack, thump)


def hit(rng):
    """Stone struck: two inharmonic partials ringing out, with a click."""
    out = []
    for i in frames(0.25):
        t = i / RATE
        ring = 0.5 * math.sin(2 * math.pi * 1420 * t) + 0.35 * math.sin(2 * math.pi * 2210 * t) + 0.2 * math.sin(2 * math.pi * 3370 * t)
        out.append(ring * env(t, 0.001, 0.12) + (rng.uniform(-1, 1) * env(t, 0.0005, 0.006)))
    return out


def ground(rng):
    """A shot into the dirt: a short, dull puff."""
    noise = lowpass([rng.uniform(-1, 1) for _ in frames(0.14)], 900)
    return [x * 1.6 * env(i / RATE, 0.002, 0.06) for i, x in enumerate(noise)]


def break_(rng):
    """A part shattering: a crunchy noise burst with grit, falling away."""
    noise = lowpass([rng.uniform(-1, 1) for _ in frames(0.6)], 2600)
    grit = [1.0 if rng.random() < 0.02 else 0.0 for _ in frames(0.6)]
    body = [(x + 0.8 * g * rng.uniform(-1, 1)) * env(i / RATE, 0.003, 0.3) for i, (x, g) in enumerate(zip(noise, grit))]
    low = [x * 0.7 * env(i / RATE, 0.004, 0.18) for i, x in enumerate(sweep(110, 45, 0.3))]
    return mix(body, low)


def stomp(rng):
    """The boss's stomp: a deep falling boom with a rumble under it."""
    boom = [x * env(i / RATE, 0.005, 0.5) for i, x in enumerate(sweep(75, 28, 0.9))]
    rumble = lowpass([rng.uniform(-1, 1) for _ in frames(0.9)], 220)
    return mix(boom, [x * 2.0 * env(i / RATE, 0.01, 0.45) for i, x in enumerate(rumble)])


def hook_fire(rng):
    """The hook thrown: a rising whoosh."""
    n = len(frames(0.3))
    noise = [rng.uniform(-1, 1) for _ in range(n)]
    out, y = [], 0.0
    for i, x in enumerate(noise):  # the band opens up as it flies
        k = 1 - math.exp(-2 * math.pi * (400 + 3000 * i / n) / RATE)
        y += k * (x - y)
        out.append(y * math.sin(math.pi * i / n))
    return out


def hook_catch(rng):
    """The hook biting: a short knock and a ring."""
    knock = [x * env(i / RATE, 0.001, 0.05) for i, x in enumerate(sweep(220, 120, 0.12))]
    ring = [0.3 * math.sin(2 * math.pi * 980 * i / RATE) * env(i / RATE, 0.001, 0.09) for i in frames(0.2)]
    return mix(knock, ring)


def hurt(rng):
    """The PC hit: a buzzy drop."""
    return [x * 0.5 * env(i / RATE, 0.003, 0.15) for i, x in enumerate(lowpass(sweep(260, 110, 0.25, square), 1800))]


SOUNDS = {"shot": (shot, 0.7), "hit": (hit, 0.6), "ground": (ground, 0.6), "break": (break_, 0.9),
          "stomp": (stomp, 0.95), "hook_fire": (hook_fire, 0.6), "hook_catch": (hook_catch, 0.8), "hurt": (hurt, 0.7)}


def render(name):
    make, peak = SOUNDS[name]
    samples = make(random.Random(name))  # its own stream per sound: adding one doesn't change the others
    top = max(1e-9, max(abs(x) for x in samples))
    data = array.array("h", (int(round(x / top * peak * 32767)) for x in samples))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(data.tobytes())
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only report whether the files are up to date")
    args = parser.parse_args()
    stale = []
    for name in SOUNDS:
        path, data = OUT / f"{name}.wav", render(name)
        if not path.exists() or path.read_bytes() != data:
            stale.append(path)
            if not args.check:
                OUT.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
    for path in stale:
        print(("stale: " if args.check else "wrote: ") + str(path.relative_to(ROOT)))
    if args.check and stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
