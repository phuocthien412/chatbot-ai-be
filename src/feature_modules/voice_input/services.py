from typing import Optional, Any, Callable
import logging

from fastapi import HTTPException, status, Request, UploadFile, Header

from src.feature_modules.voice_input.config import VoiceInputConfig as Cfg
from src.feature_modules.voice_input.schemas import TranscribeResponse
from src.feature_modules.voice_input.rate_limit import ip_limiter, client_limiter
from src.feature_modules.voice_input.validators import (
    ensure_allowed_mime,
    read_and_check_size,
)
from src.feature_modules.voice_input.adapters.openai_4o import transcribe_openai
from src.feature_modules.voice_input.audio.transcode import to_wav_16k_mono

async def _maybe_await(func: Callable[..., Any], *args, **kwargs):
    res = func(*args, **kwargs)
    if hasattr(res, "__await__"):
        return await res
    return res

def _client_ip(req: Request) -> str:
    xff = req.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return req.client.host if req.client else "unknown"

def _require_access_key_if_configured(access_key_hdr: Optional[str]) -> None:
    allowed = Cfg.allowed_access_keys()
    if not allowed:
        return
    if not access_key_hdr or access_key_hdr not in allowed:
        raise HTTPException(status_code=401, detail="Unauthorized STT access.")

async def rate_limit_check(req: Request, client_id: Optional[str]) -> None:
    ip = _client_ip(req)
    if not ip_limiter.allow(f"stt:ip:{ip}", Cfg.PER_IP_PER_MIN):
        raise HTTPException(status_code=429, detail="Too many STT requests from this IP. Please slow down.")
    if client_id:
        if not client_limiter.allow(f"stt:client:{client_id}", Cfg.PER_CLIENT_PER_MIN):
            raise HTTPException(status_code=429, detail="Too many STT requests for this client. Please slow down.")

async def transcribe_request(
    *,
    request: Request,
    upload: UploadFile,
    lang: Optional[str],
    tenant_id: Optional[str],
    x_client_id: Optional[str],
    x_access_key: Optional[str],
) -> TranscribeResponse:
    # Feature toggle
    if not Cfg.enabled():
        raise HTTPException(status_code=503, detail="STT is disabled.")

    # Optional shared-secret auth for cross-site usage
    _require_access_key_if_configured(x_access_key)

    # Rate limits
    await rate_limit_check(request, x_client_id or tenant_id)

    # Validate input
    ensure_allowed_mime(upload, Cfg.ALLOWED_MIME, Cfg.ALLOWED_EXT)
    raw = await read_and_check_size(upload, Cfg.MAX_BYTES)

    # Optional force-transcode
    prepared_bytes = raw
    prepared_name = upload.filename or "audio"
    if Cfg.FORCE_WAV:
        try:
            prepared_bytes = to_wav_16k_mono(raw)
            prepared_name = "audio.wav"
        except Exception as e:
            logging.exception("FFmpeg fallback failed")
            raise HTTPException(status_code=415, detail=f"Cannot normalize audio: {(str(e) or '')[:200]}") from e

    # Provider chain
    last_error: Optional[HTTPException] = None
    for provider in Cfg.provider_chain():
        model = None
        if provider in ("openai-4o-mini", "openai_4o_mini", "4o-mini"):
            model = "gpt-4o-mini-transcribe"
        elif provider in ("openai-4o", "4o"):
            model = "gpt-4o-transcribe"
        elif provider in ("whisper-1", "whisper"):
            model = "whisper-1"
        else:
            continue  # unknown provider token

        try:
            text = await transcribe_openai(
                model=model,
                audio_bytes=prepared_bytes,
                filename_hint=prepared_name,
                lang_hint=lang or Cfg.DEFAULT_LANG,
                timeout_s=120,
            )
            engine = model
            return TranscribeResponse(
                text=text.strip(),
                confidence=None,
                lang=(lang or Cfg.DEFAULT_LANG),
                duration_ms=None,
                engine=engine,
            )
        except HTTPException as e:
            # If OpenAI rejected media and we haven't forced WAV yet, try one time with ffmpeg
            if e.status_code in (400, 415) and not Cfg.FORCE_WAV:
                try:
                    logging.info("Retrying with ffmpeg-transcoded WAV due to provider 4xx...")
                    prepared_bytes = to_wav_16k_mono(raw)
                    prepared_name = "audio.wav"
                    # retry same model once
                    text = await transcribe_openai(
                        model=model,
                        audio_bytes=prepared_bytes,
                        filename_hint=prepared_name,
                        lang_hint=lang or Cfg.DEFAULT_LANG,
                        timeout_s=120,
                    )
                    engine = model
                    return TranscribeResponse(
                        text=text.strip(),
                        confidence=None,
                        lang=(lang or Cfg.DEFAULT_LANG),
                        duration_ms=None,
                        engine=engine,
                    )
                except HTTPException as e2:
                    last_error = e2
                    continue
            last_error = e
            continue
        except Exception as e:
            logging.exception("STT upstream unexpected error")
            last_error = HTTPException(status_code=502, detail=f"Upstream STT error: {e.__class__.__name__}")
            continue

    # If all providers failed
    if last_error:
        raise last_error
    raise HTTPException(status_code=502, detail="No STT provider available.")
