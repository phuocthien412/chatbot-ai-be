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

    # Run the chat turn
    message_id, reply, suggestions = await chat_turn(session_id, body.message)

    # Fetch message for created_at
    msg_doc = await messages_repo.get_message(message_id)
    created_at = msg_doc.get("created_at") if isinstance(msg_doc, dict) else None

    return {
        "session_id": session_id,
        "message_id": message_id,
        "reply": reply,
        "suggestions": suggestions,
        "created_at": created_at,
    }
