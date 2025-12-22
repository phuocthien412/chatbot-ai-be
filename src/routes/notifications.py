from __future__ import annotations
from typing import List, Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query

from ..repositories import notifications_repo

router = APIRouter(prefix="/admin/notifications", tags=["admin-notifications"])


class NotificationCreate(BaseModel):
    title: str
    message: str
    type: Literal["success", "error", "warning", "info"] = "info"
    module: str
    target_name: Optional[str] = None
    meta: Optional[dict] = Field(default=None, description="Optional extra payload")


class NotificationOut(BaseModel):
    id: str
    title: str
    message: str
    type: str
    module: str
    is_read: bool
    created_at: Optional[datetime] = None
    target_name: Optional[str] = None
    meta: dict = Field(default_factory=dict)

    class Config:
        populate_by_name = True


@router.get("", response_model=List[NotificationOut])
async def list_notifications(
    is_read: Optional[bool] = Query(default=None),
    module: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
):
    docs = await notifications_repo.list_notifications(
        is_read=is_read, module=module, limit=limit, skip=skip
    )
    return docs


@router.get("/unread-count")
async def unread_count():
    return {"unread": await notifications_repo.unread_count()}


@router.post("", response_model=NotificationOut)
async def create_notification(body: NotificationCreate):
    doc = await notifications_repo.create_notification(
        title=body.title,
        message=body.message,
        type_=body.type,
        module=body.module,
        target_name=body.target_name,
        meta=body.meta,
    )
    return doc


@router.post("/{notification_id}/read")
async def mark_as_read(notification_id: str):
    updated = await notifications_repo.mark_as_read(notification_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_as_read():
    count = await notifications_repo.mark_all_as_read()
    return {"ok": True, "updated": count}


@router.delete("/{notification_id}")
async def delete_notification(notification_id: str):
    deleted = await notifications_repo.delete_notification(notification_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}
