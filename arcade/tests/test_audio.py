"""Megalith's music on alia-engine's mixer: the headless test engine renders it with audio.mix()."""

import array
import json
import wave

import pytest

import audio
from arena import ENGINE

RATE = 22050  # the tracks' rate (tools/audio_build.py); the mixer resamples to 48 kHz


@pytest.fixture
def music(tmp_path):
    """Two tiny tracks: a loop (ramp 0..9999, loops from sample 3000) and a one-shot of constant 1000."""
    def write(name, samples):
        with wave.open(str(tmp_path / f"{name}.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
            w.writeframes(array.array("h", samples).tobytes())
    write("loop", range(10000))
    write("once", [1000] * 1500)
    (tmp_path / "music.json").write_text(json.dumps({"loop": {"loop_start": 3000 / RATE}, "once": {}}))
    m = audio.Music(ENGINE, tmp_path)
    yield m
    m.close()
    ENGINE.audio.mix(int(48000 * (audio.FADE + 0.1)))  # a crossfade may still be fading out: the next test starts silent


def heard(seconds):
    """Peak level (either channel) of the next `seconds`."""
    return max(abs(x) for x in array.array("f", ENGINE.audio.mix(int(48000 * seconds))))


def test_loop_keeps_going_past_its_end(music):
    music.play("loop")
    heard(0.6)  # 10000 samples at 22 kHz is 0.45 s: it has wrapped by now
    assert heard(0.1) > 0.01 and ENGINE.audio.voices == 1


def test_one_shot_plays_once_then_stays_quiet(music):
    music.play("once")
    assert heard(0.07) > 0.0  # 70 ms long, inside the 0.4 s fade-in: quiet, but there
    heard(0.6)
    music.play("once")  # still asked for: no replay
    assert heard(0.2) == 0.0
    music.play("loop", 0.5)
    heard(0.5)
    assert heard(0.1) > 0.01


def test_switching_crossfades(music):
    music.play("loop")
    heard(0.5)
    music.play("once")
    ENGINE.audio.mix(1200)  # 25 ms: the one-shot (70 ms) still plays, the loop is fading out
    assert ENGINE.audio.voices == 2  # both while they cross
    heard(0.5)
    assert ENGINE.audio.voices <= 1


def test_missing_folder_plays_nothing(tmp_path):
    m = audio.Music(ENGINE, tmp_path)
    m.play("bgm_battle")
    assert heard(0.1) == 0.0
