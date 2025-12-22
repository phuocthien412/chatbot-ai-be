from datetime import datetime, timezone
from typing import Optional, Dict, Any
from bson import ObjectId
from ..db.mongo import get_db

def _as_public(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return doc
    out = dict(doc)
    # normalize id to string for API
    if isinstance(out.get("_id"), ObjectId):
        out["_id"] = str(out["_id"])
    return out

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _to_oid(id_str: str):
    try:
        return ObjectId(id_str)
    except Exception:
        return None

async def get_session(session_id: str) -> Optional[dict]:
    db = get_db()
    # Try ObjectId match first, fallback to legacy string
    oid = _to_oid(session_id)
    doc = None
    if oid is not None:
        doc = await db.sessions.find_one({"_id": oid})
    if doc is None:
        doc = await db.sessions.find_one({"_id": session_id})
    return _as_public(doc)

async def create_session() -> dict:
    db = get_db()
    now = _now_utc()
    doc = {
        # no explicit _id: let Mongo assign ObjectId
        "status": "active",
        "created_at": now,
        "last_activity_at": now,
        "last_message_at": None,
        "last_sender": None,
        "unread_admin": 0,
        "handoff_mode": "bot",
    }
    res = await db.sessions.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _as_public(doc)

async def touch_session(session_id: str) -> None:
    db = get_db()
    oid = _to_oid(session_id)
    update = {"$set": {"last_activity_at": _now_utc()}}
    if oid is not None:
        await db.sessions.update_one({"_id": oid}, update)
    else:
        await db.sessions.update_one({"_id": session_id}, update)

async def bump_session_message(
    session_id: str,
    sender: str,
    content_preview: Optional[str] = None,
    reset_unread_admin: bool = False,
) -> None:
    """
    Update session metadata when a message is added.
    - sender: "user" | "assistant" | "admin" | "system"
    """
    db = get_db()
    now = _now_utc()
    oid = _to_oid(session_id)
    preview = (content_preview or "").strip()
    preview = preview[:300] if preview else None

    inc = {}
    if sender == "user" and not reset_unread_admin:
        inc = {"unread_admin": 1}
    set_fields = {
        "last_activity_at": now,
        "last_message_at": now,
        "last_sender": sender,
    }
    if preview is not None:
        set_fields["last_message_preview"] = preview
    if reset_unread_admin:
        set_fields["unread_admin"] = 0

    update = {"$set": set_fields}
    if inc:
        update["$inc"] = inc

    if oid is not None:
        await db.sessions.update_one({"_id": oid}, update)
    else:
        await db.sessions.update_one({"_id": session_id}, update)

async def set_handoff_mode(session_id: str, mode: str) -> None:
    db = get_db()
    oid = _to_oid(session_id)
    update = {"$set": {"handoff_mode": mode, "status": "active"}}
    if oid is not None:
        await db.sessions.update_one({"_id": oid}, update)
    else:
        await db.sessions.update_one({"_id": session_id}, update)

async def mark_inactive(session_id: str) -> None:
    """Mark session as inactive (end conversation)."""
    db = get_db()
    oid = _to_oid(session_id)
    update = {
        "$set": {
            "status": "inactive",
            "handoff_mode": "bot",
            "last_activity_at": _now_utc(),
        }
    }
    if oid is not None:
        await db.sessions.update_one({"_id": oid}, update)
    else:
        await db.sessions.update_one({"_id": session_id}, update)

async def list_sessions_raw(
    status: Optional[str] = None,
    handoff_mode: Optional[str] = None,
    limit: int = 50,
) -> list:
    db = get_db()
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if handoff_mode:
        query["handoff_mode"] = handoff_mode
    cur = (
        db.sessions.find(query)
        .sort([("last_message_at", -1), ("created_at", -1)])
        .limit(max(1, min(limit, 200)))
    )
    out = []
    async for s in cur:
        out.append(_as_public(s))
    return out
