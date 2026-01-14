from __future__ import annotations
from typing import Optional, Any, Dict
from datetime import datetime, timedelta

from src.config import settings
from src.repositories import settings_repo

# Simple in-memory cache with TTL to avoid extra round-trips on every turn
_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = timedelta(seconds=15)


def _get_cached(key: str) -> Optional[Any]:
    entry = _cache.get(key)
    if not entry:
        return None
    if entry["expires_at"] <= datetime.utcnow():
        _cache.pop(key, None)
        return None
    return entry["value"]


def _set_cached(key: str, value: Any):
    _cache[key] = {"value": value, "expires_at": datetime.utcnow() + _CACHE_TTL}


def _safe_session_ttl(value: int) -> int:
    """
    Clamp session TTL (seconds). Lower bound 5 minutes, upper bound 24h.
    """
    try:
        v = int(value)
    except Exception:
        v = 1800
    return max(60, min(v, 86_400))


def _safe_refresh_leeway(value: int) -> int:
    """
    Clamp session refresh leeway (seconds). Lower bound 10s, upper bound 10m.
    """
    try:
        v = int(value)
    except Exception:
        v = 60
    return max(10, min(v, 600))


async def get_request_timeout_seconds() -> int:
    """
    Returns the effective request timeout (seconds), falling back to env default.
    Uses a short-lived cache; stored in Mongo under key 'request_timeout_seconds'.
    """
    cached = _get_cached("request_timeout_seconds")
    if cached is not None:
        return int(cached)

    raw = await settings_repo.get_setting("request_timeout_seconds")
    if raw is None:
        value = settings.request_timeout_seconds
    else:
        try:
            value = max(5, min(int(raw), 600))
        except Exception:
            value = settings.request_timeout_seconds

    _set_cached("request_timeout_seconds", value)
    return value


async def update_request_timeout_seconds(value: int) -> int:
    safe = max(5, min(int(value), 600))
    await settings_repo.set_setting("request_timeout_seconds", safe)
    _set_cached("request_timeout_seconds", safe)
    return safe


async def get_session_ttl_seconds() -> int:
    """
    Returns the effective session TTL (seconds) for user JWTs.
    Falls back to env JWT_TTL_SECONDS (or 1800) and caches briefly.
    """
    cached = _get_cached("session_ttl_seconds")
    if cached is not None:
        return int(cached)

    default_ttl = _safe_session_ttl(getattr(settings, "jwt_ttl_seconds", None) or 1800)

    raw = await settings_repo.get_setting("session_ttl_seconds")
    if raw is None:
        value = default_ttl
    else:
        value = _safe_session_ttl(raw)

    _set_cached("session_ttl_seconds", value)
    return value


async def update_session_ttl_seconds(value: int) -> int:
    safe = _safe_session_ttl(value)
    await settings_repo.set_setting("session_ttl_seconds", safe)
    _set_cached("session_ttl_seconds", safe)
    return safe


async def get_session_refresh_leeway_seconds() -> int:
    """
    Returns how many seconds before expiry we should proactively refresh user tokens.
    Defaults to 60 seconds if unset.
    """
    cached = _get_cached("session_refresh_leeway_seconds")
    if cached is not None:
        return int(cached)

    raw = await settings_repo.get_setting("session_refresh_leeway_seconds")
    if raw is None:
        value = 60
    else:
        value = _safe_refresh_leeway(raw)

    _set_cached("session_refresh_leeway_seconds", value)
    return value


async def update_session_refresh_leeway_seconds(value: int) -> int:
    safe = _safe_refresh_leeway(value)
    await settings_repo.set_setting("session_refresh_leeway_seconds", safe)
    _set_cached("session_refresh_leeway_seconds", safe)
    return safe


async def _get_str_setting(key: str, default: str) -> str:
    cached = _get_cached(key)
    if cached is not None:
        return str(cached)
    raw = await settings_repo.get_setting(key)
    value = str(raw).strip() if raw not in (None, "") else str(default or "")
    _set_cached(key, value)
    return value


async def _set_str_setting(key: str, value: str) -> str:
    safe = str(value or "").strip()
    await settings_repo.set_setting(key, safe)
    _set_cached(key, safe)
    return safe


def _clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        v = int(value)
    except Exception:
        v = int(default)
    return max(min_value, min(v, max_value))


async def _get_int_setting(key: str, default: int, min_value: int, max_value: int) -> int:
    cached = _get_cached(key)
    if cached is not None:
        return int(cached)
    raw = await settings_repo.get_setting(key)
    value = _clamp_int(raw, default, min_value, max_value) if raw is not None else _clamp_int(default, default, min_value, max_value)
    _set_cached(key, value)
    return value


async def _set_int_setting(key: str, value: int, min_value: int, max_value: int) -> int:
    safe = _clamp_int(value, value, min_value, max_value)
    await settings_repo.set_setting(key, safe)
    _set_cached(key, safe)
    return safe


async def get_openai_model_base() -> str:
    return await _get_str_setting("openai_model", settings.openai_model)


async def get_openai_model_actor() -> str:
    base = await get_openai_model_base()
    return await _get_str_setting("openai_model_actor", settings.openai_model_actor or base)


async def get_openai_model_picker() -> str:
    base = await get_openai_model_base()
    return await _get_str_setting("openai_model_picker", settings.openai_model_picker or base)


async def get_openai_model_ticket_gen() -> str:
    base = await get_openai_model_base()
    return await _get_str_setting("openai_model_ticket_gen", settings.openai_model_ticket_gen or base)


async def get_openai_model_rag() -> str:
    base = await get_openai_model_base()
    return await _get_str_setting("openai_model_rag", settings.openai_model_rag or base)


async def get_openai_model_vision() -> str:
    base = await get_openai_model_base()
    return await _get_str_setting("openai_model_vision", settings.openai_model_vision or settings.openai_model_actor or base)


async def get_openai_model_tts() -> str:
    base = await get_openai_model_base()
    return await _get_str_setting("openai_model_tts", settings.openai_model_tts or base)


async def get_openai_tts_voice() -> str:
    return await _get_str_setting("openai_tts_voice", settings.openai_tts_voice or "alloy")


async def get_tts_default_format() -> str:
    return await _get_str_setting("tts_default_format", settings.tts_default_format or "mp3")


async def get_prompt_char_budget() -> int:
    return await _get_int_setting("prompt_char_budget", settings.prompt_char_budget, 1000, 500_000)


async def get_single_message_char_limit() -> int:
    return await _get_int_setting("single_message_char_limit", settings.single_message_char_limit, 1000, 100_000)


async def get_ai_config() -> Dict[str, Any]:
    return {
        "openai_model": await get_openai_model_base(),
        "openai_model_picker": await get_openai_model_picker(),
        "openai_model_actor": await get_openai_model_actor(),
        "openai_model_ticket_gen": await get_openai_model_ticket_gen(),
        "openai_model_rag": await get_openai_model_rag(),
        "openai_model_vision": await get_openai_model_vision(),
        "openai_model_tts": await get_openai_model_tts(),
        "openai_tts_voice": await get_openai_tts_voice(),
        "tts_default_format": await get_tts_default_format(),
        "prompt_char_budget": await get_prompt_char_budget(),
        "single_message_char_limit": await get_single_message_char_limit(),
        "request_timeout_seconds": await get_request_timeout_seconds(),
    }


async def update_ai_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "openai_model" in payload:
        await _set_str_setting("openai_model", payload.get("openai_model"))
    if "openai_model_picker" in payload:
        await _set_str_setting("openai_model_picker", payload.get("openai_model_picker"))
    if "openai_model_actor" in payload:
        await _set_str_setting("openai_model_actor", payload.get("openai_model_actor"))
    if "openai_model_ticket_gen" in payload:
        await _set_str_setting("openai_model_ticket_gen", payload.get("openai_model_ticket_gen"))
    if "openai_model_rag" in payload:
        await _set_str_setting("openai_model_rag", payload.get("openai_model_rag"))
    if "openai_model_vision" in payload:
        await _set_str_setting("openai_model_vision", payload.get("openai_model_vision"))
    if "openai_model_tts" in payload:
        await _set_str_setting("openai_model_tts", payload.get("openai_model_tts"))
    if "openai_tts_voice" in payload:
        await _set_str_setting("openai_tts_voice", payload.get("openai_tts_voice"))
    if "tts_default_format" in payload:
        await _set_str_setting("tts_default_format", payload.get("tts_default_format"))
    if "prompt_char_budget" in payload:
        await _set_int_setting("prompt_char_budget", payload.get("prompt_char_budget"), 1000, 500_000)
    if "single_message_char_limit" in payload:
        await _set_int_setting("single_message_char_limit", payload.get("single_message_char_limit"), 1000, 100_000)
    if "request_timeout_seconds" in payload:
        await update_request_timeout_seconds(payload.get("request_timeout_seconds"))
    return await get_ai_config()
