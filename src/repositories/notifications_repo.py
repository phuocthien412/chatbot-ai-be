from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4
from pymongo import ReturnDocument

from ..db.mongo import get_db


def _now() -> datetime:
    # Normalize to UTC aware datetime for consistent sorting
    return datetime.now(timezone.utc).replace(microsecond=0)


def _present(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert internal Mongo doc to API-friendly dict."""
    if not doc:
        return {}
    return {
        "id": str(doc.get("_id")),
        "title": doc.get("title"),
        "message": doc.get("message"),
        "type": doc.get("type"),
        "module": doc.get("module"),
        "is_read": bool(doc.get("is_read")),
        "created_at": doc.get("created_at"),
        "target_name": doc.get("target_name"),
        "meta": doc.get("meta") or {},
    }


async def create_notification(
    title: str,
    message: str,
    type_: str,
    module: str,
    target_name: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    db = get_db()
    doc = {
        "_id": str(uuid4()),
        "title": title,
        "message": message,
        "type": type_,
        "module": module,
        "is_read": False,
        "created_at": _now(),
        "target_name": target_name,
        "meta": meta or {},
    }
    await db.notifications.insert_one(doc)
    return _present(doc)


async def upsert_conversation_notification(
    session_id: str,
    conversation_code: Optional[str],
    tenant_id: Optional[str],
    message_preview: Optional[str],
) -> Dict[str, Any]:
    """
    Ensure there is only one notification per conversation.
    Subsequent messages update the preview and mark it unread again.
    """
    db = get_db()
    preview = (message_preview or "User sent a message").strip()
    title = f"Conversation: {tenant_id or 'Unknown'}"
    query = {"module": "conversation", "meta.conversation_id": session_id}
    update = {
        "$set": {
            "title": title,
            "message": preview[:300],
            "type": "info",
            "module": "conversation",
            "is_read": False,
            "target_name": tenant_id,
            "meta": {
                "conversation_id": session_id,
                "conversation_code": conversation_code,
            },
        },
        "$setOnInsert": {
            "_id": str(uuid4()),
            "created_at": _now(),
        },
    }
    doc = await db.notifications.find_one_and_update(
        query,
        update,
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return _present(doc)


async def list_notifications(
    is_read: Optional[bool] = None,
    module: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
) -> List[Dict[str, Any]]:
    db = get_db()
    query: Dict[str, Any] = {}
    if is_read is not None:
        query["is_read"] = is_read
    if module:
        query["module"] = module

    cur = (
        db.notifications.find(query)
        .sort("created_at", -1)
        .skip(max(skip, 0))
        .limit(max(1, min(limit, 500)))
    )
    return [_present(doc) async for doc in cur]


async def unread_count() -> int:
    db = get_db()
    return await db.notifications.count_documents({"is_read": False})


async def mark_as_read(notification_id: str) -> bool:
    db = get_db()
    result = await db.notifications.update_one(
        {"_id": notification_id}, {"$set": {"is_read": True}}
    )
    return result.modified_count > 0


async def mark_all_as_read() -> int:
    db = get_db()
    result = await db.notifications.update_many(
        {"is_read": False}, {"$set": {"is_read": True}}
    )
    return result.modified_count or 0


async def delete_notification(notification_id: str) -> bool:
    db = get_db()
    result = await db.notifications.delete_one({"_id": notification_id})
    return result.deleted_count > 0
