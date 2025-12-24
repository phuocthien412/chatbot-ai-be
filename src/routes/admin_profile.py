from __future__ import annotations
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, model_validator

from src.security.deps import RequestContext, admin_guard
from src.repositories.admin_users_repo import (
    get_admin_by_email,
    get_admin_by_id,
    verify_password,
    hash_password,
    update_admin_profile,
    update_admin_password_hash,
)

router = APIRouter(prefix="/admin/profile", tags=["admin.profile"])


class AdminProfile(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    roles: list[str] = Field(default_factory=list)
    avatar_url: Optional[str] = None
    last_login_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True


class UpdateProfilePayload(BaseModel):
    display_name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Display name shown in the admin UI",
    )
    avatar_url: Optional[str] = Field(
        default=None,
        max_length=250000,
        description="Data URL or hosted URL for the avatar image",
    )


class ChangePasswordPayload(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    new_password_hash: Optional[str] = Field(default=None, min_length=24, max_length=512)

    @model_validator(mode="after")
    def validate_new_password(self) -> "ChangePasswordPayload":
        if not self.new_password and not self.new_password_hash:
            raise ValueError("new_password or new_password_hash is required")
        return self


def _extract_admin_id(ctx: RequestContext) -> Optional[str]:
    sid = ctx.sid or ""
    if sid.startswith("admin:"):
        return sid.split("admin:", 1)[1]
    return sid or None


def _extract_admin_email(ctx: RequestContext) -> Optional[str]:
    sub = ctx.sub or ""
    if sub.startswith("admin:"):
        return sub.split("admin:", 1)[1]
    return None


async def _load_admin(ctx: RequestContext) -> dict:
    admin_id = _extract_admin_id(ctx)
    user = await get_admin_by_id(admin_id) if admin_id else None
    if user is None:
        email = _extract_admin_email(ctx)
        user = await get_admin_by_email(email) if email else None
    if not user:
        raise HTTPException(status_code=404, detail="Admin not found")
    return user


def _to_profile(doc: dict) -> AdminProfile:
    return AdminProfile(
        id=str(doc.get("_id")),
        email=doc.get("email", ""),
        display_name=doc.get("display_name") or doc.get("email") or "",
        roles=doc.get("roles") or [],
        avatar_url=doc.get("avatar_url"),
        last_login_at=doc.get("last_login_at"),
        updated_at=doc.get("updated_at"),
    )


@router.get("/me", response_model=AdminProfile)
async def get_profile(ctx: RequestContext = Depends(admin_guard)) -> AdminProfile:
    user = await _load_admin(ctx)
    return _to_profile(user)


@router.put("", response_model=AdminProfile)
async def update_profile(
    payload: UpdateProfilePayload,
    ctx: RequestContext = Depends(admin_guard),
) -> AdminProfile:
    user = await _load_admin(ctx)
    updated = await update_admin_profile(
        user.get("_id"),
        display_name=payload.display_name,
        avatar_url=payload.avatar_url,
    )
    if updated is None:
        raise HTTPException(status_code=500, detail="Could not update profile")
    return _to_profile(updated)


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordPayload,
    ctx: RequestContext = Depends(admin_guard),
) -> dict:
    user = await _load_admin(ctx)
    stored_hash = user.get("password_hash") or ""
    if not stored_hash or not verify_password(payload.current_password, stored_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if payload.new_password_hash:
        if not payload.new_password_hash.startswith("pbkdf2_sha256$"):
            raise HTTPException(status_code=400, detail="new_password_hash must be PBKDF2-SHA256")
        new_hash = payload.new_password_hash
    else:
        new_hash = hash_password(payload.new_password or "")

    ok = await update_admin_password_hash(user.get("_id"), new_hash)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update password")

    return {"ok": True}
