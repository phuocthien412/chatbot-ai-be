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
