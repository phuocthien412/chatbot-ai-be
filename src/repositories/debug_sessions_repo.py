from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from bson import ObjectId

from ..db.mongo import get_db


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_public(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return doc
    out = dict(doc)
    if isinstance(out.get("_id"), ObjectId):
        out["_id"] = str(out["_id"])
    return out


async def create_session(language: Optional[str] = None) -> dict:
    db = get_db()
    now = _now_utc()
    from src.services.runtime_settings import get_session_ttl_seconds
    ttl = await get_session_ttl_seconds()
    expires_at = now + timedelta(seconds=ttl)
    doc = {
        "status": "active",
        "created_at": now,
        "expires_at": expires_at,
        "last_activity_at": now,
        "last_message_at": None,
        "last_sender": None,
    }
    if language:
        doc["language"] = language
    res = await db.debug_sessions.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _as_public(doc)


async def touch_session(session_id: str) -> None:
    db = get_db()
    try:
        oid = ObjectId(session_id)
    except Exception:
        oid = None
    update = {"$set": {"last_activity_at": _now_utc()}}
    if oid is not None:
        await db.debug_sessions.update_one({"_id": oid}, update)
    else:
        await db.debug_sessions.update_one({"_id": session_id}, update)
