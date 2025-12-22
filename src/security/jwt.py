# src/security/jwt.py
from __future__ import annotations
import time
from typing import Dict, Any, Optional
import jwt  # PyJWT

from src.config import settings  # use pydantic settings as source of truth


def _secret() -> str:
    if not settings.jwt_secret:
        # Fail fast instead of silently using a weak default
        raise RuntimeError("JWT_SECRET is required (set env JWT_SECRET)")
    return settings.jwt_secret


def _issuer() -> str:
    return settings.jwt_issuer or "chatbot-be"


def _ttl_seconds() -> int:
    """Default TTL (seconds) for *user* tokens.

    Falls back to 1800s if JWT_TTL_SECONDS is unset or invalid.
    """
    try:
        return int(settings.jwt_ttl_seconds) if settings.jwt_ttl_seconds is not None else 1800
    except Exception:
        return 1800


def issue_jwt(
    sub: str,
    sid: str,
    tid: str,
    role: str = "user",
    ttl_seconds: Optional[int] = None,
) -> str:
    """Mint a signed JWT.

    Args:
        sub: subject (e.g. "guest:abcd1234" or "admin:email")
        sid: session identifier. For end-users this is the chat session id;
             for admins we use a logical id like "admin:<user_id>".
        tid: tenant id or logical partition ("default", "admin", etc.).
        role: "user" or "admin".
        ttl_seconds: optional override for token TTL. If None or invalid,
                     falls back to _ttl_seconds().
    """
    now = int(time.time())
    # Resolve TTL
    if ttl_seconds is None:
        ttl = _ttl_seconds()
    else:
        try:
            ttl = int(ttl_seconds)
        except Exception:
            ttl = _ttl_seconds()
    if ttl <= 0:
        ttl = _ttl_seconds()

    payload: Dict[str, Any] = {
        "iss": _issuer(),
        "sub": sub,
        "sid": sid,
        "tid": tid,
        "role": role,
        "iat": now,
        "exp": now + ttl,
    }
    token = jwt.encode(payload, _secret(), algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def verify_jwt(token: str) -> Dict[str, Any]:
    data = jwt.decode(
        token,
        _secret(),
        algorithms=["HS256"],
        options={"require": ["exp", "iat", "iss"]},
    )
    if data.get("iss") != _issuer():
        raise jwt.InvalidIssuerError("Issuer mismatch")
    return data
