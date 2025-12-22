import httpx
from fastapi import HTTPException
from typing import Optional

from src.feature_modules.voice_input.config import VoiceInputConfig as Cfg
from src.feature_modules.voice_input.env_loader import ensure_feature_env

# OpenAI Audio Transcriptions endpoint (multipart)
# POST {OPENAI_API_BASE}/v1/audio/transcriptions
# form: file=@..., model=..., language=vi (optional), response_format=json (default)

def _lang_to_openai(lang_hint: Optional[str]) -> Optional[str]:
    if not lang_hint:
        return None
    code = lang_hint.strip().lower()
    # Normalize common forms
    if code in {"vi", "vi-vn", "vn"}:
        return "vi"
    return code  # let API decide

async def transcribe_openai(
    *,
    model: str,                    # "gpt-4o-mini-transcribe" | "gpt-4o-transcribe" | "whisper-1"
    audio_bytes: bytes,
    filename_hint: str = "audio",
    lang_hint: Optional[str] = None,
    timeout_s: int = 90,
) -> str:
    # Ensure env presence (feature-local .env.voice_input or root .env)
    ensure_feature_env(["OPENAI_API_KEY"])

    api_key = Cfg.openai_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="STT provider misconfigured: missing OPENAI_API_KEY")

    url = f"{Cfg.openai_api_base().rstrip('/')}/v1/audio/transcriptions"

    # Build multipart form
    files = {
        "file": (filename_hint, audio_bytes, "application/octet-stream"),
        "model": (None, model),
    }
    lang = _lang_to_openai(lang_hint)
    if lang:
        files["language"] = (None, lang)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(url, headers=headers, files=files)

    if resp.status_code == 401:
        raise HTTPException(status_code=500, detail="STT provider auth failed (OpenAI 401).")
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="STT provider rate limited (OpenAI 429).")
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="STT provider server error (OpenAI 5xx).")
    if resp.status_code >= 400:
        # Often 400 when media is odd; let caller decide if they want to ffmpeg and retry.
        detail = (resp.text or "")[:300]
        raise HTTPException(status_code=415, detail=f"STT provider rejected audio (OpenAI 4xx): {detail}")

    data = resp.json()
    # OpenAI returns {"text": "..."} for json format
    text = data.get("text")
    if not text:
        raise HTTPException(status_code=502, detail="STT provider returned no text.")
    return text
