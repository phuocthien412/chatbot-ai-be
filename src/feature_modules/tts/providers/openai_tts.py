import httpx
from fastapi import HTTPException
from typing import Tuple, Dict
import os

from src.config import settings  # loads .env via Pydantic BaseSettings

def _resolve_api_base() -> str:
    return os.getenv("OPENAI_API_BASE", "https://api.openai.com").rstrip("/")

def _resolve_api_key() -> str:
    # Prefer settings (works even if values come from .env only)
    if getattr(settings, "openai_api_key", None):
        return settings.openai_api_key
    # Fallback to raw env for completeness
    return os.getenv("OPENAI_API_KEY", "")

def _resolve_model() -> str:
    return (
        (getattr(settings, "openai_model_tts", None) or "")
        or os.getenv("OPENAI_TTS_MODEL", "")
        or os.getenv("OPENAI_MODEL_TTS", "")
        or getattr(settings, "openai_model", "gpt-4o-mini-tts")
    )

def _resolve_default_voice() -> str:
    return getattr(settings, "openai_tts_voice", None) or os.getenv("OPENAI_TTS_VOICE", "alloy")

def _map_voice(logical: str) -> str:
    return logical or _resolve_default_voice()

async def synthesize_bytes(text: str, voice: str, fmt: str, speed: float, pitch: int) -> Tuple[bytes, Dict]:
    api_key = _resolve_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY missing for TTS.")
    model = _resolve_model()
    voice = _map_voice(voice)
    response_format = fmt  # "mp3" | "opus" | "wav"

    url = f"{_resolve_api_base()}/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": response_format,
        "speed": float(speed or 1.0),
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 429:
            raise HTTPException(status_code=429, detail="TTS provider rate limited (OpenAI 429).")
        if resp.status_code >= 500:
            raise HTTPException(status_code=502, detail="TTS provider server error (OpenAI 5xx).")
        if resp.status_code >= 400:
            detail = (resp.text or "")[:300]
            raise HTTPException(status_code=415, detail=f"TTS provider rejected input (OpenAI 4xx): {detail}")
        audio_bytes = resp.content
        if not audio_bytes:
            raise HTTPException(status_code=502, detail="TTS provider returned empty audio.")
        meta = {"provider": "openai", "model": model, "voice": voice, "format": response_format}
        return audio_bytes, meta
