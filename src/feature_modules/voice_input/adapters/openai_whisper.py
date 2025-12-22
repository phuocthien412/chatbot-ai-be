from fastapi import HTTPException
from openai import OpenAI, APIConnectionError, APIStatusError

from src.feature_modules.voice_input.config import VoiceInputConfig as Cfg
from src.feature_modules.voice_input.env_loader import ensure_voice_env

def _client() -> OpenAI:
    ensure_voice_env(["OPENAI_API_KEY"])
    key = Cfg.openai_api_key()
    if not key:
        raise HTTPException(status_code=500, detail="STT misconfigured: missing OPENAI_API_KEY")
    return OpenAI(api_key=key)

def transcribe_whisper(*, audio_bytes: bytes, filename_hint: str, lang: str | None):
    client = _client()
    try:
        # Whisper also uses the transcriptions endpoint
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_bytes,  # SDK may accept raw bytes; if not, use a NamedTemporaryFile (same pattern as above)
            language=lang if lang else None,
        )
    except APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"Upstream STT error: {e.status_code} {e.response.text[:200]}") from e
    except APIConnectionError as e:
        raise HTTPException(status_code=502, detail="Upstream STT connection error") from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream STT error: {e.__class__.__name__}") from e

    text = getattr(resp, "text", None) or (resp.get("text") if isinstance(resp, dict) else None)
    if not text:
        raise HTTPException(status_code=422, detail="STT recognized no text.")
    return text
