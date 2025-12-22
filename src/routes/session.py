# src/routes/session.py
from __future__ import annotations
from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter
from pydantic import BaseModel, Field
from bson import ObjectId

from src.security.jwt import issue_jwt
from src.db.mongo import get_db
from src.config import settings
from .chat import router as _chat_router

router = APIRouter(prefix="/session", tags=["session"])

class StartRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="Tenant id; default 'default'")

class StartResponse(BaseModel):
    session_id: str
    token: str
    expires_in: int
    tenant_id: str

@router.post("/start", response_model=StartResponse)
async def start(req: StartRequest) -> StartResponse:
    tenant_id = (req.tenant_id or "default").strip() or "default"

    ttl = int(settings.jwt_ttl_seconds) if settings.jwt_ttl_seconds is not None else 1800
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
    )

class EndRequest(BaseModel):
  session_id: str

@router.post("/end")
async def end_session(req: EndRequest):
    """Mark a session as inactive when user resets conversation."""
    await sessions_repo.mark_inactive(req.session_id)
    return {"ok": True, "status": "inactive", "session_id": req.session_id}
