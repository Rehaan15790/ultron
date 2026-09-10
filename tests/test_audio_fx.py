"""Tests for the local pitch-shift pass."""
import io
from pathlib import Path

import av
import pytest

from src.voice.audio_fx import deepen


SAMPLE = Path(__file__).parent / "fixtures" / "speech_sample.mp3"


def duration_seconds(mp3_bytes: bytes) -> float:
    with av.open(io.BytesIO(mp3_bytes)) as c:
        return c.duration / 1_000_000


@pytest.fixture(scope="module")
def original() -> bytes:
    # A tracked fixture, so a missing file is a broken checkout - fail loudly
    # rather than skipping and reporting green.
    assert SAMPLE.exists(), f"missing tracked fixture: {SAMPLE}"
    return SAMPLE.read_bytes()


def test_pitch_shift_preserves_duration(original):
    """
    The whole point of the asetrate+atempo chain: a genuine pitch shift, not a
    slowed-down tape. If atempo were dropped, this would be ~12% longer.
    """
    shifted = deepen(original, 0.89)
    before, after = duration_seconds(original), duration_seconds(shifted)
    assert abs(after - before) < 0.15, f"{before:.2f}s -> {after:.2f}s"


def test_pitch_shift_produces_decodable_audio(original):
    shifted = deepen(original, 0.94)
    with av.open(io.BytesIO(shifted)) as c:
        frames = sum(1 for _ in c.decode(c.streams.audio[0]))
    assert frames > 0


def test_pitch_shift_actually_changes_the_audio(original):
    assert deepen(original, 0.89) != original


def test_factor_of_one_is_a_no_op(original):
    assert deepen(original, 1.0) is original


def test_empty_input_is_returned_unchanged():
    assert deepen(b"", 0.9) == b""


def test_corrupt_audio_returns_input_rather_than_raising():
    """A failed effect must never cost the user their audio."""
    junk = b"this is not an mp3"
    assert deepen(junk, 0.9) == junk


def test_pitch_bounds_are_enforced_by_config():
    from pydantic import ValidationError
    from src.config import Settings

    Settings(VOICE_PITCH=0.85)          # in range
    with pytest.raises(ValidationError):
        Settings(VOICE_PITCH=0.5)       # too deep to sound like a voice
    with pytest.raises(ValidationError):
        Settings(VOICE_PITCH=1.4)       # this stage only lowers pitch
