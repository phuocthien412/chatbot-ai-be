from __future__ import annotations
from typing import Any, Dict, Optional

from ..repositories import notifications_repo
from .events import broadcast_event


async def log_notification(
    *,
    title: str,
    message: str,
    type_: str = "info",
    module: str,
    target_name: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Persist an admin notification for later display.

    Args:
        title: Short title.
        message: Human-readable body.
        type_: success|error|warning|info.
        module: Logical module name (prompts, ticket-types, system, etc).
        target_name: Optional target identifier.
        meta: Optional extra data for future UI use.
    """
    doc = await notifications_repo.create_notification(
        title=title,
        message=message,
        type_=type_,
        module=module,
        target_name=target_name,
        meta=meta,
    )
    try:
        await broadcast_event({"type": "notification.created", "data": doc})
    except Exception:
        pass
    return doc
