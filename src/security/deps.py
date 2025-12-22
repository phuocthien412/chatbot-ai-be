from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from bson import ObjectId

from .jwt import verify_jwt
from src.config import settings
from src.db.mongo import get_db

# File access helpers (unchanged behavior)
try:
    from src.repositories.files_repo import get_file as repo_get_file
except Exception:
    repo_get_file = None
try:
    from src.feature_modules.file_content.config import PUBLIC_BY_ID
except Exception:
    PUBLIC_BY_ID = False

bearer_scheme = HTTPBearer(auto_error=False)

@dataclass
class RequestContext:
    sub: str
    sid: str
    tid: str
    role: str
    raw: Dict[str, Any]

async def auth_user(
    req: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> RequestContext:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    try:
        payload = verify_jwt(creds.credentials)
    except Exception as e:
        # ExpiredSignatureError etc.
        raise HTTPException(status_code=401, detail=f"Invalid token: {type(e).__name__}")
    sid = payload.get("sid")
    if not sid:
        raise HTTPException(status_code=401, detail="Token missing sid")
    return RequestContext(
        sub=payload.get("sub", "guest"),
        sid=sid,
        tid=payload.get("tid", "default"),
        role=payload.get("role", "user"),
        raw=payload,
    )

async def admin_guard(ctx: RequestContext = Depends(auth_user)) -> RequestContext:
    if ctx.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return ctx

async def enforce_sid_binding(
    request: Request,
    ctx: RequestContext = Depends(auth_user),
) -> None:
    """
    Bind effective session to JWT.sid. If request provides session_id and it's different -> 403.
    Works for JSON and form-data. Missing session_id is allowed.
    """
    ctype = (request.headers.get("content-type") or "").lower()

    if "application/json" in ctype:
        try:
            body = await request.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            sid_in = body.get("session_id")
            if sid_in and str(sid_in) != ctx.sid:
                raise HTTPException(status_code=403, detail="session_id mismatch")
        return

    if "multipart/form-data" in ctype or "application/x-www-form-urlencoded" in ctype:
        try:
            form = await request.form()
            sid_in = form.get("session_id")
            if sid_in and str(sid_in) != ctx.sid:
                raise HTTPException(status_code=403, detail="session_id mismatch")
        except Exception:
            pass
        return

    return

async def session_alive_guard(ctx: RequestContext = Depends(auth_user)) -> None:
    """
    Ensure the session referenced by JWT.sid exists and is not expired.
    If the session doc is missing, or expired based on expires_at (or created_at+TTL fallback), return 401.
    """

    def _normalize_dt(value):
        """Return a timezone-aware datetime in UTC."""
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    # Resolve the session doc
    db = get_db()
    try:
        oid = ObjectId(ctx.sid)
    except Exception:
        raise HTTPException(status_code=401, detail="session invalid")

    doc = await db.sessions.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=401, detail="session invalid")

    now = datetime.now(timezone.utc)
    ttl = int(settings.jwt_ttl_seconds) if settings.jwt_ttl_seconds is not None else 1800

    expires_at = doc.get("expires_at")
    if not expires_at:
        # Backfill rule for legacy docs: created_at + TTL; if missing, treat as invalid.
        created_at = doc.get("created_at")
        if created_at:
            created_at = _normalize_dt(created_at)
            expires_at = created_at + timedelta(seconds=ttl) if created_at else None
        else:
            raise HTTPException(status_code=401, detail="session invalid")
    else:
        expires_at = _normalize_dt(expires_at)

    if not expires_at:
        raise HTTPException(status_code=401, detail="session invalid")

    if now >= expires_at:
        raise HTTPException(status_code=401, detail="session expired")

async def file_access_guard(
    request: Request,
    ctx: RequestContext = Depends(auth_user),
) -> None:
    """
    File download guard: must own the file (file.session_id == jwt.sid).
    Note: session expiry is enforced separately via session_alive_guard in main.py.
    """
    file_id = request.path_params.get("file_id")
    if not file_id or repo_get_file is None:
        return
    doc = await repo_get_file(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")
    owner = str(doc.get("session_id") or "")
    if not owner:
        if PUBLIC_BY_ID:
            return
        raise HTTPException(status_code=403, detail="Forbidden")
    if owner != ctx.sid:
        raise HTTPException(status_code=403, detail="Forbidden")
