import array
import json
import wave

import pytest

import audio


@pytest.fixture
def music(tmp_path, monkeypatch):
    """Music with two tiny tracks and no aplay: a loop (ramp 0..9999, loops from sample 3000)
    and a one-shot of constant 1000."""
    def write(name, samples):
        with wave.open(str(tmp_path / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(audio.RATE)
            w.writeframes(array.array("h", samples).tobytes())
    write("loop", range(10000))
    write("once", [1000] * 1500)
    (tmp_path / "music.json").write_text(json.dumps({"loop": {"loop_start": 3000 / audio.RATE, "end": 1},
                                                     "once": {"end": 1}}))
    monkeypatch.setattr(audio, "MASTER", 1.0)  # full scale: faded-in samples come out unchanged
    return audio.Music(tmp_path, sink=[])


def chunk(m):
    return array.array("h", m.next_chunk())


def test_loop_wraps_to_loop_start_without_a_gap(music):
    music.play("loop")
    for _ in range(20):
        out = chunk(music)
    assert len(out) == audio.CHUNK and music.gain == 1.0
    while music.pos < 10000 - audio.CHUNK:
        chunk(music)
    out = list(chunk(music))
    wrap = out.index(3000)
    assert out[wrap - 1] == 9999 and out[wrap:wrap + 3] == [3000, 3001, 3002]


def test_one_shot_plays_once_then_stays_quiet(music):
    music.play("once")
    heard = [chunk(music) for _ in range(4)]
    assert any(any(s) for s in heard)
    assert all(not any(chunk(music)) for _ in range(5))  # finished: silence, not a replay
    music.play("loop", 0.5)
    assert any(any(chunk(music)) for _ in range(5))


def test_switching_fades_out_before_the_next_track(music):
    music.play("loop")
    for _ in range(20):
        chunk(music)
    music.play("once")
    gains = []
    for _ in range(20):
        chunk(music)
        gains.append((music.current, round(music.gain, 3)))
    names = [n for n, _ in gains]
    assert names[0] == "loop" and "once" in names
    first_once = names.index("once")
    assert gains[first_once - 1][1] == 0.0 and gains[first_once][1] == 0.0  # faded to zero, then restarted


def test_missing_folder_plays_nothing(tmp_path):
    m = audio.Music(tmp_path, sink=[])
    m.play(None)
    assert not any(m.next_chunk())
