from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.db.mongo import get_db
from src.security.deps import RequestContext, admin_guard, super_admin_guard
from src.security.permissions import DEFAULT_ROLES, build_default_permissions

router = APIRouter(prefix="/admin/permissions", tags=["admin.permissions"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class PermissionsResponse(BaseModel):
    roles: list[dict]
    permissions: Dict[str, Dict[str, Dict[str, bool]]]
    updated_at: datetime | None = None
    updated_by: str | None = None


class PermissionsUpdate(BaseModel):
    permissions: Dict[str, Dict[str, Dict[str, bool]]] = Field(
        ...,
        description="Role -> module -> action -> allowed",
    )


@router.get("", response_model=PermissionsResponse)
async def get_permissions(ctx: RequestContext = Depends(admin_guard)) -> PermissionsResponse:  # noqa: ARG001
    db = get_db()
    doc = await db.admin_permissions.find_one({"_id": "global"})
    if not doc:
        return PermissionsResponse(
            roles=DEFAULT_ROLES,
            permissions=build_default_permissions(),
        )
    return PermissionsResponse(
        roles=DEFAULT_ROLES,
        permissions=doc.get("permissions") or build_default_permissions(),
        updated_at=doc.get("updated_at"),
        updated_by=doc.get("updated_by"),
    )


@router.put("", response_model=PermissionsResponse)
async def update_permissions(
    payload: PermissionsUpdate,
    ctx: RequestContext = Depends(super_admin_guard),
) -> PermissionsResponse:
    db = get_db()
    now = _now_utc()
    updated_by = ctx.sub or ""
    await db.admin_permissions.update_one(
        {"_id": "global"},
        {
            "$set": {
                "permissions": payload.permissions,
                "updated_at": now,
                "updated_by": updated_by,
            }
        },
        upsert=True,
    )
    return PermissionsResponse(
        roles=DEFAULT_ROLES,
        permissions=payload.permissions,
        updated_at=now,
        updated_by=updated_by,
    )
