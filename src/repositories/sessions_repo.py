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
    }
    res = await db.sessions.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _as_public(doc)

async def touch_session(session_id: str) -> None:
    db = get_db()
    oid = _to_oid(session_id)
    if oid is not None:
        await db.sessions.update_one({"_id": oid}, {"$set": {"last_activity_at": _now_utc()}})
    else:
        await db.sessions.update_one({"_id": session_id}, {"$set": {"last_activity_at": _now_utc()}})
