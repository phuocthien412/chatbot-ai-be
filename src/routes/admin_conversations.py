from __future__ import annotations
from typing import Optional, Dict, Any, List
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Body, WebSocket
from pydantic import BaseModel, Field

from src.repositories import sessions_repo, messages_repo
from src.services.chat_service import chat_turn
from src.security.deps import admin_guard, RequestContext, ADMIN_ROLES
from src.security.permissions import ensure_permission
from src.services.events import manager as ws_manager, broadcast_event
from src.security.jwt import verify_jwt

router = APIRouter(prefix="/admin/conversations", tags=["admin.conversations"])
logger = logging.getLogger(__name__)


class SendMessageBody(BaseModel):
    message: str = Field(..., description="Message content")
    mode: str = Field("bot", pattern="^(bot|admin)$")


async def _get_session_or_404(session_id: str) -> Dict[str, Any]:
    session = await sessions_repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def _filter_internal_system_breadcrumbs(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Hide internal system breadcrumbs (e.g., TOOL:create_ticket...) from admin portal views.
    """
    return [
        m for m in messages
        if not (
            (m.get("role") or "").lower() == "system"
            and str(m.get("content") or "").startswith("TOOL:")
        )
    ]


@router.get("")
async def list_conversations(
    status: Optional[str] = Query(None),
    handoff_mode: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    ctx: RequestContext = Depends(admin_guard),
) -> Dict[str, Any]:
    await ensure_permission(ctx, "conversations", "view")
    sessions = await sessions_repo.list_sessions_raw(
        status=status,
        handoff_mode=handoff_mode,
        limit=limit,
        search=search,
        include_debug=False,
    )
    sessions = [s for s in sessions if s.get("conversation_id")]
    sessions = [s for s in sessions if s.get("conversation_id")]
    return {"items": sessions, "count": len(sessions)}


@router.get("/stats")
async def get_conversation_stats(
    ctx: RequestContext = Depends(admin_guard),
) -> Dict[str, Any]:
    await ensure_permission(ctx, "conversations", "view")
    return await sessions_repo.get_conversation_stats()


@router.get("/{session_id}")
async def get_conversation(
    session_id: str,
    preview_messages: bool = Query(True),
    preview_limit: int = Query(50, ge=1, le=200),
    ctx: RequestContext = Depends(admin_guard),
) -> Dict[str, Any]:
    await ensure_permission(ctx, "conversations", "view")
    session = await _get_session_or_404(session_id)
    messages: List[Dict[str, Any]] = []
    if preview_messages:
        messages = await messages_repo.list_messages(session_id, limit=preview_limit)
        messages = _filter_internal_system_breadcrumbs(messages)
    return {"session": session, "messages": messages}


@router.get("/{session_id}/messages")
async def get_conversation_messages(
    session_id: str,
    limit: int = Query(100, ge=1, le=500),
    ctx: RequestContext = Depends(admin_guard),
) -> Dict[str, Any]:
    await ensure_permission(ctx, "conversations", "view")
    await _get_session_or_404(session_id)
    messages = await messages_repo.list_messages(session_id, limit=limit)
    messages = _filter_internal_system_breadcrumbs(messages)
    return {"items": messages, "count": len(messages)}


@router.post("/{session_id}/messages")
async def send_conversation_message(
    session_id: str,
    payload: SendMessageBody = Body(...),
    ctx: RequestContext = Depends(admin_guard),
) -> Dict[str, Any]:
    await ensure_permission(ctx, "conversations", "reply")
    await _get_session_or_404(session_id)
    text = (payload.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="message required")

    if payload.mode == "admin":
        msg = await messages_repo.create_admin_message(session_id, text)
        await sessions_repo.set_handoff_mode(session_id, "admin", admin_id=ctx.sub or ctx.sid)
        await broadcast_event({"type": "message.created", "data": msg})
        try:
            from src.services.user_events import broadcast_to_user
            await broadcast_to_user(session_id, {"type": "message.created", "data": msg})
        except Exception:
            pass
        await broadcast_event({
            "type": "conversation.updated",
            "data": {
                "session_id": session_id,
                "last_message_at": msg.get("created_at"),
                "last_sender": "admin",
                "handoff_mode": "admin",
                "takeover_admin": ctx.sub or ctx.sid,
                "status": "active",
            },
        })
        return {"mode": "admin", "message": msg}

    # mode == bot: treat as user input and let bot reply
    assistant_message_id, reply, suggestions = await chat_turn(session_id, text)
    recent = await messages_repo.list_messages(session_id, limit=2)
    for m in recent:
        await broadcast_event({"type": "message.created", "data": m})
        try:
            from src.services.user_events import broadcast_to_user
            if (m.get("role") or "").lower() == "system" and str(m.get("content") or "").startswith("TOOL:"):
                continue  # hide internal breadcrumbs from end-users
            await broadcast_to_user(session_id, {"type": "message.created", "data": m})
        except Exception:
            pass
    await broadcast_event({
        "type": "conversation.updated",
        "data": {
            "session_id": session_id,
            "last_message_at": recent[-1].get("created_at") if recent else None,
            "last_sender": recent[-1].get("sender") or recent[-1].get("role") if recent else None,
            "handoff_mode": "bot",
        },
    })
    return {
        "mode": "bot",
        "assistant_message_id": assistant_message_id,
        "reply": reply,
        "suggestions": suggestions,
    }


@router.post("/{session_id}/handoff")
async def set_handoff(
    session_id: str,
    mode: str = Body(..., embed=True),
    ctx: RequestContext = Depends(admin_guard),
) -> Dict[str, Any]:
    await ensure_permission(ctx, "conversations", "handoff")
    if mode not in ("bot", "admin"):
        raise HTTPException(status_code=400, detail="mode must be bot|admin")
    await _get_session_or_404(session_id)
    await sessions_repo.set_handoff_mode(session_id, mode, admin_id=ctx.sub or ctx.sid)
    await broadcast_event({
        "type": "handoff.changed",
        "data": {"session_id": session_id, "handoff_mode": mode, "takeover_admin": ctx.sub or ctx.sid},
    })
    await broadcast_event({
        "type": "conversation.updated",
        "data": {
            "session_id": session_id,
            "handoff_mode": mode,
            "status": "active",
            "takeover_admin": ctx.sub or ctx.sid,
        },
    })
    return {"ok": True, "handoff_mode": mode}


@router.websocket("/ws")
async def conversations_ws(websocket: WebSocket):
    """
    Admin-only WebSocket. Expect query param ?token=BearerToken
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()
        if not token:
            await websocket.close(code=4401)
            return
    try:
        payload = verify_jwt(token)
        if payload.get("role") not in ADMIN_ROLES:
            await websocket.close(code=4403)
            return
    except Exception as exc:
        logger.warning("Admin WS token verify failed: %s", exc)
        await websocket.close(code=4401)
        return

    await ws_manager.connect(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                try:
                    await websocket.send_text("pong")
                except Exception:
                    break
                continue
    except Exception:
        await ws_manager.disconnect(websocket)


@router.post("/{session_id}/read")
async def mark_conversation_read(session_id: str, ctx: RequestContext = Depends(admin_guard)):
    await ensure_permission(ctx, "conversations", "view")
    await sessions_repo.mark_read(session_id)
    return {"ok": True}


@router.delete("/{session_id}")
async def delete_conversation(session_id: str, ctx: RequestContext = Depends(admin_guard)):
    await ensure_permission(ctx, "conversations", "delete")
    success = await sessions_repo.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_conversations_read(ctx: RequestContext = Depends(admin_guard)):
    await ensure_permission(ctx, "conversations", "view")
    count = await sessions_repo.mark_all_read()
    return {"ok": True, "updated": count}
