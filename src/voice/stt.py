"""Local speech-to-text via faster-whisper.

Audio never leaves the machine: the browser records it, POSTs it to this
process, and Whisper runs on the local GPU (falling back to CPU).
"""
import io
import os
import sys
import sysconfig
import threading
import time
from pathlib import Path

from src.config import settings
from src.security.audit import audit


def _nvidia_bin_dirs() -> list[Path]:
    """Locate the bin/ folders inside the pip-installed CUDA runtime packages."""
    roots: list[Path] = []

    # Importing the namespace package is the only reliable way to find it in a
    # venv: site.getsitepackages() reports the base interpreter's paths, not the
    # venv's, so globbing those finds nothing.
    try:
        import nvidia
        roots.extend(Path(p) for p in nvidia.__path__)
    except ImportError:
        pass

    roots.append(Path(sysconfig.get_paths()["purelib"]) / "nvidia")

    bins: list[Path] = []
    for root in roots:
        if root.is_dir():
            bins.extend(d for d in root.glob("*/bin") if d.is_dir())
    return sorted(set(bins))


def _add_cuda_dll_dirs() -> None:
    """
    The CUDA runtime ships inside pip packages (nvidia/cublas/bin,
    nvidia/cudnn/bin) which are not on PATH, so CTranslate2 cannot load
    cublas64_12.dll on its own. Register those directories with the loader.
    """
    if sys.platform != "win32":
        return

    dirs = _nvidia_bin_dirs()
    for bin_dir in dirs:
        try:
            os.add_dll_directory(str(bin_dir))
        except (OSError, AttributeError):
            pass

    # add_dll_directory does not cover every load path CTranslate2 takes, so
    # put the directories on PATH as well.
    if dirs:
        existing = os.environ.get("PATH", "")
        prefix = os.pathsep.join(str(d) for d in dirs)
        if prefix not in existing:
            os.environ["PATH"] = prefix + os.pathsep + existing


class Transcriber:
    """Lazily-loaded Whisper model. Thread-safe, loaded once on first use."""

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self.device = None
        self.model_name = None

    def _candidates(self) -> list[tuple[str, str, str]]:
        """(device, compute_type, model) in preference order."""
        if settings.STT_DEVICE == "cpu":
            return [("cpu", "int8", settings.STT_MODEL_CPU)]
        gpu = [("cuda", "float16", settings.STT_MODEL_GPU)]
        if settings.STT_DEVICE == "cuda":
            return gpu
        # "auto": try GPU, fall back to CPU rather than failing the request.
        return gpu + [("cpu", "int8", settings.STT_MODEL_CPU)]

    def load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model

            _add_cuda_dll_dirs()
            from faster_whisper import WhisperModel

            errors = []
            for device, compute_type, model_name in self._candidates():
                try:
                    t0 = time.time()
                    model = WhisperModel(model_name, device=device, compute_type=compute_type)
                    self._model = model
                    self.device = device
                    self.model_name = model_name
                    audit.log_event("stt.model_loaded", {
                        "model": model_name,
                        "device": device,
                        "compute_type": compute_type,
                        "load_seconds": round(time.time() - t0, 2),
                    })
                    return model
                except Exception as e:
                    errors.append(f"{device}/{model_name}: {type(e).__name__}: {e}")

            audit.log_event("stt.model_load_failed", {"attempts": errors})
            raise RuntimeError("Could not load any speech model. Tried: " + " | ".join(errors))

    def transcribe(self, audio: bytes) -> str:
        """Decode raw audio bytes (webm/ogg/wav/mp3) to text. Returns '' for silence."""
        model = self.load()
        segments, _info = model.transcribe(
            io.BytesIO(audio),
            beam_size=settings.STT_BEAM_SIZE,
            language=settings.STT_LANGUAGE or None,
            # Drop non-speech so a click-and-say-nothing does not hallucinate text.
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        return " ".join(segment.text for segment in segments).strip()


# Singleton - the model is expensive to load, so keep exactly one.
transcriber = Transcriber()
