"""Standalone smoke test for ElevenLabs voice output.

Reads credentials from .env via src.config - no keys in source.
Run: python test_voice_direct.py
"""
from elevenlabs import save, ElevenLabs
from src.config import settings

if not settings.voice_enabled:
    raise SystemExit(
        "ELEVENLABS_API_KEY / ULTRON_VOICE_ID are not set. "
        "Copy .env.example to .env and fill them in."
    )

print("1. Connecting to ElevenLabs...")
client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)

print("2. Generating audio...")
audio = client.text_to_speech.convert(
    voice_id=settings.ULTRON_VOICE_ID,
    text="I am Ultron. Systems are online.",
    model_id="eleven_flash_v2_5",
)

print("3. Saving file...")
save(audio, "ultron_test.mp3")

print("4. SUCCESS! Play ultron_test.mp3 in your folder.")
