"""Tests for local speech-to-text."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config import settings
from src.voice import stt


PROJECT_ROOT = Path(__file__).parent.parent
SAMPLE_AUDIO = PROJECT_ROOT / "ultron_test.mp3"


@pytest.fixture(scope="module")
def client():
    from src.server import app
    with TestClient(app) as c:
        yield c


# --- Device selection ---

def test_auto_prefers_gpu_then_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(settings, "STT_DEVICE", "auto")
    devices = [c[0] for c in stt.Transcriber()._candidates()]
    assert devices == ["cuda", "cpu"], "auto must degrade to CPU instead of failing"


def test_explicit_cpu_never_tries_cuda(monkeypatch):
    monkeypatch.setattr(settings, "STT_DEVICE", "cpu")
    assert [c[0] for c in stt.Transcriber()._candidates()] == ["cpu"]


def test_explicit_cuda_does_not_silently_downgrade(monkeypatch):
    monkeypatch.setattr(settings, "STT_DEVICE", "cuda")
    assert [c[0] for c in stt.Transcriber()._candidates()] == ["cuda"]


def test_cuda_dll_dirs_are_discoverable_in_a_venv():
    """
    site.getsitepackages() reports the base interpreter's paths inside a venv,
    so the original lookup found nothing and CTranslate2 failed to load
    cublas64_12.dll at inference time. Guard the fix.
    """
    dirs = stt._nvidia_bin_dirs()
    if not dirs:
        pytest.skip("CUDA runtime packages not installed")
    assert all(d.is_dir() for d in dirs)
    assert any(d.name == "bin" for d in dirs)


# --- HTTP surface ---

def test_transcribe_rejects_empty_upload(client):
    r = client.post("/transcribe", files={"audio": ("empty.webm", b"", "audio/webm")})
    assert r.status_code == 400


def test_transcribe_rejects_oversized_upload(client, monkeypatch):
    monkeypatch.setattr(settings, "STT_MAX_UPLOAD_BYTES", 10)
    r = client.post("/transcribe", files={"audio": ("big.webm", b"x" * 100, "audio/webm")})
    assert r.status_code == 413


def test_transcribe_requires_an_audio_field(client):
    assert client.post("/transcribe").status_code == 422


def test_transcribe_reports_failure_without_crashing(client, monkeypatch):
    def boom(_raw):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(stt.transcriber, "transcribe", boom)
    r = client.post("/transcribe", files={"audio": ("a.webm", b"not audio", "audio/webm")})
    assert r.status_code == 503
    assert "error" in r.json()


# --- Real transcription (slow: loads the model) ---

@pytest.mark.skipif(not SAMPLE_AUDIO.exists(), reason="no sample audio present")
def test_end_to_end_transcription(client):
    with open(SAMPLE_AUDIO, "rb") as f:
        r = client.post("/transcribe", files={"audio": ("sample.mp3", f.read(), "audio/mpeg")})

    if r.status_code == 503:
        pytest.skip("speech model unavailable in this environment")

    assert r.status_code == 200
    text = r.json()["text"].lower()
    assert "ultron" in text
    assert "online" in text
