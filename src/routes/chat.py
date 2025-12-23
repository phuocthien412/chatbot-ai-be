from __future__ import annotations
"""
Chat route: POST /chat

Request body:
{
  "session_id": "optional",
  "message": "string"
}

Response body:
{
  "session_id": "...",
  "message_id": "...",
  "reply": "...",
  "suggestions": ["...", "..."],
  "created_at": "ISO-8601"
}
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, Body
from pydantic import BaseModel

from src.repositories import sessions_repo, messages_repo
from src.services.chat_service import chat_turn
from src.services.events import broadcast_event
from src.services.user_events import broadcast_to_user

router = APIRouter(prefix="/chat", tags=["chat"])

class ChatBody(BaseModel):
    session_id: Optional[str] = None
    message: str

@router.post("")
async def post_chat(body: ChatBody = Body(...)) -> Dict[str, Any]:
    # Ensure session exists or create
    session_id = body.session_id
    if session_id:
        session = await sessions_repo.get_session(session_id)
        if not session:
            # auto create a new session if provided id not found
            session = await sessions_repo.create_session()
            session_id = session["_id"]
    else:
        session = await sessions_repo.create_session()
        session_id = session["_id"]

    # If session was timeout, reactivate bot mode on new user message
    if session.get("status") == "timeout":
        await sessions_repo.set_handoff_mode(session_id, "bot")

    # If admin takeover, do not let bot respond
    if session.get("handoff_mode") == "admin":
        user_msg = await messages_repo.create_user_message(session_id, body.message)
        await broadcast_event({"type": "message.created", "data": user_msg})
        await broadcast_to_user(session_id, {"type": "message.created", "data": user_msg})
        await broadcast_event({
            "type": "conversation.updated",
            "data": {
                "session_id": session_id,
                "handoff_mode": "admin",
                "last_message_at": user_msg.get("created_at"),
                "last_sender": "user",
            },
        })
        return {
            "session_id": session_id,
            "message_id": user_msg.get("_id"),
            "reply": None,
            "suggestions": [],
            "handoff_mode": "admin",
            "note": "Admin takeover mode - bot will not respond",
        }

    # Run the chat turn
    message_id, reply, suggestions = await chat_turn(session_id, body.message)

    # Fetch message for created_at
    msg_doc = await messages_repo.get_message(message_id)
    created_at = msg_doc.get("created_at") if isinstance(msg_doc, dict) else None

    # Broadcast to admin listeners (best-effort)
    try:
        # send last two messages for context
        msgs = await messages_repo.list_messages(session_id, limit=2)
        await broadcast_event({
            "type": "conversation.updated",
            "data": {
                "session_id": session_id,
                "last_message_at": created_at,
                "last_sender": "assistant",
            },
        })
        for m in msgs:
            await broadcast_event({"type": "message.created", "data": m})
            await broadcast_to_user(session_id, {"type": "message.created", "data": m})
    except Exception:
        pass

    return {
        "session_id": session_id,
        "message_id": message_id,
        "reply": reply,
        "suggestions": suggestions,
        "created_at": created_at,
    }
