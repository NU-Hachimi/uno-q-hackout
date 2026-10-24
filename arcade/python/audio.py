"""Background music on the MPU: one long-running `aplay` fed raw PCM by a thread.

Keeping one `aplay` open means a loop has no gap and switching tracks never reopens the device.
In the App Lab container `aplay -D default` reaches the board's headphone jack through PipeWire.
Tracks are python/music/*.wav (tools/audio_build.py); music.json says which ones loop and from where.
"""

import array
import json
import shutil
import subprocess
import threading
import wave
from pathlib import Path

RATE = 22050
CHUNK = 1024              # samples per write, 46 ms
FADE = 0.4                # s to fade out before the next track starts, and for volume changes
MASTER = 0.8              # overall music level; the system volume stays as the board has it
FOLDER = Path(__file__).resolve().parent / "music"
APLAY = ["aplay", "-q", "-D", "default", "-t", "raw", "-f", "S16_LE", "-r", str(RATE), "-c", "1",
         "--buffer-time=200000", "-"]  # 0.2 s of buffering keeps a switch responsive


class Music:
    """play(name, volume) whenever the wanted music may have changed; it is cheap when nothing did."""

    def __init__(self, folder=FOLDER, sink=None):
        self.folder = Path(folder)
        self.table = json.loads((self.folder / "music.json").read_text()) if (self.folder / "music.json").exists() else {}
        self.cache = {}
        self.lock = threading.Lock()
        self.wanted, self.wanted_volume = None, 0.0
        self.current, self.pos, self.gain, self.done = None, 0, 0.0, None
        self.step = CHUNK / (FADE * RATE)  # gain change per chunk
        self.sink, self.process = sink, None
        if sink is None:
            self._start()

    def _start(self):
        if not shutil.which("aplay") or not self.table:
            print("music: no aplay or no tracks, playing nothing")
            return
        try:
            self.process = subprocess.Popen(APLAY, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as error:
            print(f"music: cannot start aplay: {error}")
            return
        self.sink = self.process.stdin
        threading.Thread(target=self._run, daemon=True).start()

    def play(self, name, volume=1.0):
        """Wanted track (None for silence) and its level 0..1. A one-shot that has finished stays quiet
        until something else has been played."""
        with self.lock:
            self.wanted, self.wanted_volume = name, max(0.0, min(1.0, volume)) * MASTER

    def _samples(self, name):
        if name not in self.cache:
            with wave.open(str(self.folder / f"{name}.wav")) as w:
                self.cache[name] = array.array("h", w.readframes(w.getnframes()))
        return self.cache[name]

    def next_chunk(self):
        """The next CHUNK samples as bytes: follows the wanted track, fading across a change."""
        with self.lock:
            wanted, level = self.wanted, self.wanted_volume
        if wanted != self.current:
            if self.current is not None and self.gain > 0:  # fade the old track out first
                self.gain = max(0.0, self.gain - self.step)
            elif wanted != self.done:
                self.current, self.pos, self.gain, self.done = wanted, 0, 0.0, None
            else:
                self.current = None  # the finished one-shot is still wanted: stay quiet
        elif self.gain != level:
            self.gain = min(level, self.gain + self.step) if self.gain < level else max(level, self.gain - self.step)
        if self.current is None:
            return bytes(2 * CHUNK)
        samples, track = self._samples(self.current), self.table.get(self.current, {})
        out = samples[self.pos:self.pos + CHUNK]
        self.pos += len(out)
        while len(out) < CHUNK:
            if "loop_start" not in track:  # one-shot finished
                self.done, self.current = self.current, None
                out.extend(array.array("h", bytes(2 * (CHUNK - len(out)))))
                break
            self.pos = int(track["loop_start"] * RATE)
            more = samples[self.pos:self.pos + CHUNK - len(out)]
            self.pos += len(more)
            out.extend(more)
        if self.gain < 0.999:
            out = array.array("h", (int(s * self.gain) for s in out))
        return out.tobytes()

    def _run(self):
        try:
            while True:
                self.sink.write(self.next_chunk())  # blocks while aplay's buffer is full
        except (BrokenPipeError, OSError, ValueError):
            print("music: aplay stopped")

    def close(self):
        if self.process:
            self.process.kill()
