from __future__ import annotations
from typing import Any, Optional
from datetime import datetime

from src.db.mongo import get_db


async def get_setting(key: str) -> Optional[Any]:
    """Fetch a setting value by key."""
    db = get_db()
    doc = await db.app_settings.find_one({"_id": key})
    if not doc:
        return None
    return doc.get("value")


async def set_setting(key: str, value: Any) -> None:
    """Upsert a setting value by key."""
    db = get_db()
    await db.app_settings.update_one(
        {"_id": key},
        {
            "$set": {
                "value": value,
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )
