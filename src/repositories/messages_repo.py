from __future__ import annotations
"""
repositories/messages_repo.py

Message persistence helpers.

Schema (collection: messages)
- _id: ObjectId   (returned to callers as **string** for JSON-friendliness)
- session_id: ObjectId (stored)
- role: "user" | "assistant" | "system" | "tool"
- content: str
- created_at: ISO-8601 string (UTC)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from bson import ObjectId

from ..db.mongo import get_db
from . import sessions_repo

# --- internal helpers ---------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _to_oid(id_str: str):
    try:
        return ObjectId(id_str)
    except Exception:
        return None

def _as_public(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy with IDs coerced to str for API safety."""
    if not doc:
        return doc
    out = dict(doc)
    if isinstance(out.get("_id"), ObjectId):
        out["_id"] = str(out["_id"])
    if isinstance(out.get("session_id"), ObjectId):
        out["session_id"] = str(out["session_id"])
    return out

# --- create -------------------------------------------------------------------

async def _create(
    session_id: str,
    role: str,
    content: str,
    sender: Optional[str] = None,
) -> Dict[str, Any]:
    db = get_db()
    sid_oid = _to_oid(session_id)
    doc: Dict[str, Any] = {
        # no explicit _id => let Mongo assign ObjectId
        "session_id": sid_oid if sid_oid is not None else session_id,
        "role": role,
        "content": content,
        "created_at": _iso_now(),
    }
    if sender:
        doc["sender"] = sender
    res = await db.messages.insert_one(doc)
    doc["_id"] = res.inserted_id  # ObjectId
    public_doc = _as_public(doc)
    try:
        reset_unread = role in ("assistant", "system") or sender == "admin"
        await sessions_repo.bump_session_message(
            session_id,
            sender=sender or role,
            content_preview=content,
            reset_unread_admin=reset_unread,
        )
    except Exception:
        # Do not break message creation on session bump failure
        pass
    return public_doc

async def create_user_message(session_id: str, content: str) -> Dict[str, Any]:
    return await _create(session_id, "user", content)

async def create_assistant_message(session_id: str, content: str) -> Dict[str, Any]:
    return await _create(session_id, "assistant", content)

async def create_admin_message(session_id: str, content: str) -> Dict[str, Any]:
    return await _create(session_id, "assistant", content, sender="admin")

async def create_system_message(session_id: str, content: str) -> Dict[str, Any]:
    return await _create(session_id, "system", content)

async def create_tool_message(session_id: str, content: str) -> Dict[str, Any]:
    return await _create(session_id, "tool", content)

# --- read ---------------------------------------------------------------------

async def list_messages(session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    db = get_db()
    sid_oid = _to_oid(session_id)
    # Try OID first; if no hits, fallback to legacy string session_id
    query = {"session_id": sid_oid} if sid_oid is not None else {"session_id": session_id}
    cur = db.messages.find(query).sort("created_at", 1).limit(limit)
    out: List[Dict[str, Any]] = []
    async for m in cur:
        out.append(_as_public(m))
    # fallback when OID was used but collection still has legacy strings
    if sid_oid is not None and not out:
        cur2 = db.messages.find({"session_id": session_id}).sort("created_at", 1).limit(limit)
        async for m in cur2:
            out.append(_as_public(m))
    return out

async def get_message(message_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single message by its _id (accepts ObjectId string or legacy str)."""
    db = get_db()
    doc: Optional[Dict[str, Any]] = None
    try:
        oid = ObjectId(message_id)
        doc = await db.messages.find_one({"_id": oid})
    except Exception:
        doc = None
    if doc is None:
        doc = await db.messages.find_one({"_id": message_id})
    return _as_public(doc) if doc else None
