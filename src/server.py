import asyncio
import os
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.config import settings
from src.main import process_input
from src.security.audit import audit
from src.tools.p1_tools import read_cpu_percent, read_ram_percent
from src.voice.stt import transcriber
from src.voice.audio_fx import deepen

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
AUDIO_DIR = STATIC_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Number of generated clips to keep on disk before pruning the oldest.
AUDIO_RETENTION = 5

client = None
if settings.voice_enabled:
    from elevenlabs import ElevenLabs
    client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the speech model in the background so the first utterance is not
    # charged the full model-load time.
    threading.Thread(target=_safe_warmup, daemon=True).start()
    yield


def _safe_warmup():
    try:
        transcriber.load()
    except Exception as e:
        audit.log_event("stt.warmup_failed", {"error": str(e)})


app = FastAPI(title="ULTRON HUD", lifespan=lifespan)

# Local-only HUD: no wildcard origin, no credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# StaticFiles resolves and confines paths itself - no hand-rolled traversal risk.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatMessage(BaseModel):
    text: str
    # Per-tab conversation. Absent or unknown ids get their own session rather
    # than sharing one global history.
    session_id: str = Field("default", max_length=64)


def _prune_old_audio() -> None:
    clips = sorted(AUDIO_DIR.glob("response_*.mp3"), key=lambda p: p.stat().st_mtime)
    for stale in clips[:-AUDIO_RETENTION]:
        try:
            stale.unlink()
        except OSError:
            pass


def _voice_settings():
    """
    Explicit voice settings. The configured voice has none saved on ElevenLabs'
    side, so omitting these silently applies generic defaults and the designed
    voice comes out sounding wrong.
    """
    if settings.ELEVENLABS_STABILITY is None:
        return None

    from elevenlabs import VoiceSettings
    return VoiceSettings(
        stability=settings.ELEVENLABS_STABILITY,
        similarity_boost=settings.ELEVENLABS_SIMILARITY,
        style=settings.ELEVENLABS_STYLE,
        use_speaker_boost=settings.ELEVENLABS_SPEAKER_BOOST,
    )


def _synthesize(text: str) -> str:
    """Blocking ElevenLabs call plus local pitch pass. Run off the event loop."""
    kwargs = dict(
        voice_id=settings.ULTRON_VOICE_ID,
        text=text,
        model_id=settings.ELEVENLABS_MODEL,
    )
    voice_settings = _voice_settings()
    if voice_settings is not None:
        kwargs["voice_settings"] = voice_settings

    audio_bytes = b"".join(client.text_to_speech.convert(**kwargs))
    audio_bytes = deepen(audio_bytes, settings.VOICE_PITCH)

    audio_path = AUDIO_DIR / f"response_{uuid.uuid4().hex}.mp3"
    audio_path.write_bytes(audio_bytes)
    _prune_old_audio()
    return audio_path.name


@app.get("/")
async def read_root():
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/stats")
async def stats():
    """Real host telemetry for the HUD readouts."""
    return {"cpu": read_cpu_percent(), "ram": read_ram_percent()}


@app.post("/transcribe")
async def transcribe_endpoint(audio: UploadFile = File(...)):
    """Speech to text, entirely on this machine. Returns {"text": ...}."""
    raw = await audio.read()

    if not raw:
        return JSONResponse(status_code=400, content={"error": "Empty audio upload."})
    if len(raw) > settings.STT_MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={"error": "Audio upload too large."})

    try:
        text = await asyncio.to_thread(transcriber.transcribe, raw)
    except Exception as e:
        audit.log_event("stt.error", {"error": str(e)})
        return JSONResponse(status_code=503, content={"error": "Speech recognition unavailable."})

    audit.log_event("stt.transcribed", {
        "bytes": len(raw),
        "chars": len(text),
        "device": transcriber.device,
    })
    return {"text": text}


@app.post("/chat")
async def chat_endpoint(message: ChatMessage):
    response_text = await asyncio.to_thread(process_input, message.text, message.session_id)

    audio_url = None
    if response_text and settings.voice_enabled:
        try:
            filename = await asyncio.to_thread(_synthesize, response_text)
            audio_url = f"/static/audio/{filename}"
        except Exception as e:
            audit.log_event("tts.error", {"error": str(e)})

    return {"response": response_text, "audio_url": audio_url}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Pushes telemetry so the HUD does not poll /stats on a timer."""
    await websocket.accept()
    try:
        while True:
            await websocket.send_json({
                "type": "telemetry",
                "cpu": read_cpu_percent(),
                "ram": read_ram_percent(),
            })
            await asyncio.sleep(settings.TELEMETRY_INTERVAL)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        # Anything else is a real fault worth recording, not swallowing.
        audit.log_event("ws.error", {"error": str(e)})
