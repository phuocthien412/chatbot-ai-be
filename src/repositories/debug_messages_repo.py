from __future__ import annotations

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from bson import ObjectId

from ..db.mongo import get_db
from . import debug_sessions_repo


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_oid(id_str: str):
    try:
        return ObjectId(id_str)
    except Exception:
        return None


def _as_public(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    out = dict(doc)
    if isinstance(out.get("_id"), ObjectId):
        out["_id"] = str(out["_id"])
    if isinstance(out.get("session_id"), ObjectId):
        out["session_id"] = str(out["session_id"])
    return out


async def _create(
    session_id: str,
    role: str,
    content: str,
) -> Dict[str, Any]:
    db = get_db()
    sid_oid = _to_oid(session_id)
    doc: Dict[str, Any] = {
        "session_id": sid_oid if sid_oid is not None else session_id,
        "role": role,
        "content": content,
        "created_at": _iso_now(),
    }
    res = await db.debug_messages.insert_one(doc)
    doc["_id"] = res.inserted_id
    await debug_sessions_repo.touch_session(session_id)
    return _as_public(doc)


async def create_user_message(session_id: str, content: str) -> Dict[str, Any]:
    return await _create(session_id, "user", content)


async def create_system_message(session_id: str, content: str) -> Dict[str, Any]:
    return await _create(session_id, "system", content)


async def list_messages(session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    db = get_db()
    sid_oid = _to_oid(session_id)
    query = {"session_id": sid_oid} if sid_oid is not None else {"session_id": session_id}
    cur = db.debug_messages.find(query).sort("created_at", 1).limit(limit)
    out: List[Dict[str, Any]] = []
    async for m in cur:
        out.append(_as_public(m))
    if sid_oid is not None and not out:
        cur2 = db.debug_messages.find({"session_id": session_id}).sort("created_at", 1).limit(limit)
        async for m in cur2:
            out.append(_as_public(m))
    return out
