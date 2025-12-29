# src/routes/session.py
from __future__ import annotations
from typing import Optional
from datetime import datetime, timedelta, timezone
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from bson import ObjectId

from src.security.jwt import issue_jwt
from src.security.deps import RequestContext, auth_user, session_alive_guard
from src.db.mongo import get_db
from src.config import settings
from src.services.events import broadcast_event
from src.repositories import sessions_repo
from src.services.runtime_settings import (
    get_session_ttl_seconds,
    get_session_refresh_leeway_seconds,
)
from .chat import router as _chat_router

router = APIRouter(prefix="/session", tags=["session"])

# --- helpers ------------------------------------------------------------------
_START_BUCKETS: dict[str, list[float]] = {}
_START_LIMIT = 10  # requests per window
_START_WINDOW = 60  # seconds

def _check_rate_limit(ip: str) -> None:
    """Best-effort in-memory rate limit for /session/start to reduce spam."""
    now = time.time()
    bucket = _START_BUCKETS.get(ip, [])
    bucket = [ts for ts in bucket if now - ts <= _START_WINDOW]
    if len(bucket) >= _START_LIMIT:
        raise HTTPException(status_code=429, detail="Too many session requests")
    bucket.append(now)
    _START_BUCKETS[ip] = bucket

class StartRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="Tenant id; default 'default'")

class StartResponse(BaseModel):
    session_id: str
    token: str
    expires_in: int
    tenant_id: str
    refresh_leeway_seconds: int

@router.post("/start", response_model=StartResponse)
async def start(req: StartRequest, request: Request) -> StartResponse:
    # basic per-IP rate limit (best-effort)
    try:
        client_ip = request.client.host if request.client else "unknown"
        _check_rate_limit(client_ip or "unknown")
    except HTTPException:
        raise
    except Exception:
        # do not block if client info missing
        pass

    tenant_id = (req.tenant_id or "default").strip() or "default"

    ttl = await get_session_ttl_seconds()
    leeway = await get_session_refresh_leeway_seconds()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl)

    # Create real session doc in Mongo with an explicit expiry
    db = get_db()
    oid = ObjectId()
    await db.sessions.insert_one({
        "_id": oid,
        "tenant_id": tenant_id,
        "status": "active",
        "created_at": now,
        "expires_at": expires_at,
        "last_activity_at": now,
        "last_message_at": None,
        "last_sender": None,
        "unread_admin": 0,
        "handoff_mode": "bot",
    })

    # Mint user token bound to this session
    session_id = str(oid)
    sub = f"guest:{session_id[:8]}"
    token = issue_jwt(sub=sub, sid=session_id, tid=tenant_id, role="user")

    return StartResponse(
        session_id=session_id,
        token=token,
        expires_in=ttl,
        tenant_id=tenant_id,
        refresh_leeway_seconds=leeway,
    )

class EndRequest(BaseModel):
  session_id: str

@router.post("/end")
async def end_session(
    req: EndRequest,
    ctx: RequestContext = Depends(auth_user),
    _=Depends(session_alive_guard),
):
    """
    Mark a session as inactive when user resets conversation.
    Only the owner of the session (JWT.sid) may end it.
    """
    if req.session_id != ctx.sid:
        raise HTTPException(status_code=403, detail="session_id mismatch")
    await sessions_repo.mark_inactive(req.session_id)
    try:
        await broadcast_event({
            "type": "conversation.updated",
            "data": {
                "session_id": req.session_id,
                "status": "ended",
                "handoff_mode": "bot",
            },
        })
    except Exception:
        pass
    return {"ok": True, "status": "ended", "session_id": req.session_id}


@router.post("/refresh", response_model=StartResponse)
async def refresh_session(
    ctx: RequestContext = Depends(auth_user),
    _=Depends(session_alive_guard),
) -> StartResponse:
    """
    Refresh the current user's session token and extend expiry.
    Requires a valid user JWT; keeps the same session_id (JWT.sid).
    """
    ttl = await get_session_ttl_seconds()
    leeway = await get_session_refresh_leeway_seconds()
    now = datetime.now(timezone.utc)
    new_expires = now + timedelta(seconds=ttl)

    db = get_db()
    try:
        oid = ObjectId(ctx.sid)
        query = {"_id": oid}
    except Exception:
        query = {"_id": ctx.sid}

    await db.sessions.update_one(query, {"$set": {"expires_at": new_expires, "last_activity_at": now}})

    token = issue_jwt(
        sub=ctx.sub,
        sid=ctx.sid,
        tid=ctx.tid,
        role=ctx.role or "user",
        ttl_seconds=ttl,
    )

    return StartResponse(
        session_id=ctx.sid,
        token=token,
        expires_in=ttl,
        tenant_id=ctx.tid,
        refresh_leeway_seconds=leeway,
    )
