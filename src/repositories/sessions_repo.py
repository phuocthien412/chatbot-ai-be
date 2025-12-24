from datetime import datetime, timezone
from typing import Optional, Dict, Any
import time
from bson import ObjectId
from pymongo import ReturnDocument
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


async def _generate_conversation_id() -> str:
    db = get_db()
    res = await db.counters.find_one_and_update(
        {"_id": "conversation_seq"},
        {"$inc": {"seq": 1}, "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    seq = int(res.get("seq", 1))
    return f"C{seq:06d}"


async def _ensure_conversation_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return doc
    if doc.get("conversation_id"):
        return doc
    conv_id = await _generate_conversation_id()
    db = get_db()
    await db.sessions.update_one({"_id": doc.get("_id")}, {"$set": {"conversation_id": conv_id}})
    doc["conversation_id"] = conv_id
    return doc

async def get_session(session_id: str) -> Optional[dict]:
    db = get_db()
    # Try ObjectId match first, fallback to legacy string
    oid = _to_oid(session_id)
    doc = None
    if oid is not None:
        doc = await db.sessions.find_one({"_id": oid})
    if doc is None:
        doc = await db.sessions.find_one({"_id": session_id})
    doc = await _ensure_conversation_id(doc)
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
        "conversation_id": await _generate_conversation_id(),
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

async def set_handoff_mode(session_id: str, mode: str, admin_id: Optional[str] = None) -> None:
    db = get_db()
    oid = _to_oid(session_id)
    update = {"$set": {"handoff_mode": mode, "status": "active"}}
    if admin_id:
        update["$set"]["takeover_admin"] = admin_id
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
            "status": "ended",
            "handoff_mode": "bot",
            "last_activity_at": _now_utc(),
        }
    }
    if oid is not None:
        await db.sessions.update_one({"_id": oid}, update)
    else:
        await db.sessions.update_one({"_id": session_id}, update)

async def mark_all_status(status: str) -> None:
    """Bulk update all sessions to a given status (used on prompt reload)."""
    db = get_db()
    await db.sessions.update_many({}, {"$set": {"status": status, "handoff_mode": "bot"}})

async def list_sessions_raw(
    status: Optional[str] = None,
    handoff_mode: Optional[str] = None,
    limit: int = 50,
    search: Optional[str] = None,
) -> list:
    db = get_db()
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if handoff_mode:
        query["handoff_mode"] = handoff_mode
    if search:
        query["conversation_id"] = {"$regex": search, "$options": "i"}
    cur = (
        db.sessions.find(query)
        .sort([("created_at", -1)])
        .limit(max(1, min(limit, 200)))
    )
    out = []
    async for s in cur:
        s = await _ensure_conversation_id(s)
        out.append(_as_public(s))
    return out


async def mark_read(session_id: str) -> None:
    db = get_db()
    oid = _to_oid(session_id)
    update = {"$set": {"unread_admin": 0}}
    if oid is not None:
        await db.sessions.update_one({"_id": oid}, update)
    else:
        await db.sessions.update_one({"_id": session_id}, update)


async def delete_session(session_id: str) -> bool:
    db = get_db()
    oid = _to_oid(session_id)
    query = {"_id": oid} if oid else {"_id": session_id}
    res = await db.sessions.delete_one(query)
    # cascade delete messages
    await db.messages.delete_many({"session_id": oid if oid else session_id})
    return res.deleted_count > 0


async def mark_all_read() -> int:
    """Mark all sessions as read (unread_admin = 0)."""
    db = get_db()
    res = await db.sessions.update_many(
        {"unread_admin": {"$gt": 0}},
        {"$set": {"unread_admin": 0}}
    )
    return res.modified_count
