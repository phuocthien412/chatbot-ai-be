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
