import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# This machine's TLS is intercepted (antivirus/proxy), so the intercepting CA
# lives in the Windows trust store but not in certifi's bundle. Libraries that
# pin certifi - huggingface_hub in particular - fail to download models without
# this. truststore routes verification through the OS store instead of
# disabling it. No-op if truststore is absent or the platform has no OS store.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

class Settings(BaseSettings):
    # P1 Strict Constraints
    MAX_INPUT_LENGTH: int = Field(2000, description="Max characters after normalization")
    MAX_RAW_LENGTH: int = Field(10000, description="Max characters before normalization")

    # Ollama Settings
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:14b"
    OLLAMA_TIMEOUT: float = 60.0
    # Ollama unloads an idle model after ~4 minutes by default. Reloading 9GB
    # costs over two minutes, so the first message after any pause would hang.
    # This must be a duration WITH a unit - a bare "-1" is rejected with
    # 'missing unit in duration'. Use "-1s" to pin it indefinitely.
    OLLAMA_KEEP_ALIVE: str = "24h"
    # Every reply is spoken aloud and TTS latency scales with length
    # (eleven_v3 costs roughly 28ms per character), so this doubles as the
    # main latency control. ~90 tokens lands around 250-350 characters.
    OLLAMA_NUM_PREDICT: int = Field(90, description="Max response tokens from Deep Core")

    # Voice (ElevenLabs). Set these in .env - never commit them.
    ELEVENLABS_API_KEY: str = ""
    ULTRON_VOICE_ID: str = ""
    # multilingual_v2 is the high-fidelity model. The turbo/flash models trade
    # voice similarity for latency, which makes a Voice Design ("generated")
    # voice drift noticeably away from the preview it was designed against.
    ELEVENLABS_MODEL: str = "eleven_multilingual_v2"

    # Voice settings. The 'Ultron' voice has none saved server-side, so without
    # these ElevenLabs applies its own generic defaults and the character of the
    # designed voice is lost. Set any to None to fall back to that behaviour.
    ELEVENLABS_STABILITY: float | None = 0.45
    ELEVENLABS_SIMILARITY: float | None = 0.95
    ELEVENLABS_STYLE: float | None = 0.25
    ELEVENLABS_SPEAKER_BOOST: bool = True

    # ElevenLabs bills per character. Tool output - file dumps, directory
    # trees, search hits - is both expensive and pointless to speak aloud:
    # one 2.2KB file read cost 2,262 credits of a 10,000 credit quota. Replies
    # longer than this are delivered as text only.
    TTS_MAX_CHARS: int = Field(600, description="Skip speech synthesis above this length")

    # Pitch depth applied after synthesis. ElevenLabs has no pitch control, so
    # this is a local libavfilter pass. 1.0 = untouched, lower = deeper.
    VOICE_PITCH: float = Field(1.0, ge=0.7, le=1.0)

    # Speech-to-text (local faster-whisper - audio never leaves the machine)
    STT_DEVICE: str = Field("auto", description="auto | cuda | cpu")
    STT_MODEL_GPU: str = "distil-large-v3"
    STT_MODEL_CPU: str = "small.en"
    STT_BEAM_SIZE: int = 1
    STT_LANGUAGE: str = Field("en", description="Empty string = autodetect")
    STT_MAX_UPLOAD_BYTES: int = Field(25 * 1024 * 1024, description="Reject oversized audio uploads")

    # Paths
    AUDIT_LOG_PATH: Path = Field(Path("logs/audit.jsonl"))
    AUDIT_MAX_BYTES: int = Field(2_000_000, description="Rotate the audit log past this size")
    AUDIT_BACKUP_COUNT: int = Field(3, description="Rotated audit logs to keep")

    # Telemetry push interval for the HUD websocket, in seconds.
    TELEMETRY_INTERVAL: float = 2.0

    # Stored memory limits. Every fact is injected into every system message,
    # so an unbounded store is paid for on every single turn.
    MEMORY_MAX_FACTS: int = Field(40, description="Keep only the newest N facts")
    MEMORY_MAX_FACT_LENGTH: int = Field(300, description="Reject facts longer than this")

    # Policy. Tier 0 = read-only, no side effects (clock, telemetry).
    # Tier 1 = read-only filesystem access, confined to TOOL_ROOT.
    # Nothing that writes, deletes, or executes exists yet; when it does it
    # belongs at Tier 2 and must not be enabled by default.
    ALLOWED_TIERS: list[int] = [0, 1]

    # Sandbox root for Tier 1 tools. Everything outside this is unreachable.
    TOOL_ROOT: Path = Field(Path("."), description="Project directory Ultron may read")
    FS_MAX_READ_BYTES: int = Field(100_000, description="Refuse to read files larger than this")
    FS_MAX_LINES: int = Field(300, description="Max lines returned from one file")
    FS_MAX_RESULTS: int = Field(60, description="Max entries from a list/find/search")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def voice_enabled(self) -> bool:
        """True only when both credentials are actually configured."""
        return bool(self.ELEVENLABS_API_KEY and self.ULTRON_VOICE_ID)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

settings = Settings()
