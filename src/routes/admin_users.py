from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from src.repositories.admin_users_repo import (
    create_admin_user,
    create_admin_user_with_hash,
    hash_password,
    list_admin_users,
    update_admin_roles,
    update_admin_password_hash,
    update_admin_user,
    delete_admin_user,
    verify_password,
    get_admin_by_id,
)
from src.security.deps import RequestContext, admin_guard, super_admin_guard
from src.security.permissions import ensure_permission

router = APIRouter(prefix="/admin/users", tags=["admin.users"])

ALLOWED_ROLES = {"super_admin", "admin", "owner", "dev", "user"}


def _normalize_role(value: str) -> str:
    role = value.strip().lower().replace(" ", "_").replace("-", "_")
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    return role


def _normalize_roles(values: List[str]) -> List[str]:
    if not values:
        return ["admin"]
    return [_normalize_role(v) for v in values]


class AdminUser(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    roles: List[str] = Field(default_factory=list)
    avatar_url: Optional[str] = None
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_login_at: Optional[str] = None


class CreateUserRequest(BaseModel):
    email: EmailStr
    display_name: Optional[str] = Field(default=None, max_length=120)
    password: Optional[str] = Field(default=None, min_length=1)
    password_hash: Optional[str] = Field(default=None, min_length=10)
    avatar_url: Optional[str] = Field(default=None, max_length=250000)
    roles: List[str] = Field(default_factory=lambda: ["admin"])


class UpdateRolesRequest(BaseModel):
    roles: List[str] = Field(default_factory=list)


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=120)
    avatar_url: Optional[str] = Field(default=None, max_length=250000)
    roles: Optional[List[str]] = None
    is_active: Optional[bool] = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    new_password_hash: Optional[str] = Field(default=None, min_length=24, max_length=512)


def _to_admin_user(doc: dict) -> AdminUser:
    return AdminUser(
        id=str(doc.get("_id")),
        email=doc.get("email", ""),
        display_name=doc.get("display_name") or doc.get("email") or "",
        roles=doc.get("roles") or [],
        avatar_url=doc.get("avatar_url"),
        is_active=doc.get("is_active", True),
        created_at=str(doc.get("created_at")) if doc.get("created_at") else None,
        updated_at=str(doc.get("updated_at")) if doc.get("updated_at") else None,
        last_login_at=str(doc.get("last_login_at")) if doc.get("last_login_at") else None,
    )


@router.get("", response_model=List[AdminUser])
async def list_users(_ctx: RequestContext = Depends(admin_guard)) -> List[AdminUser]:
    await ensure_permission(_ctx, "users", "view")
    docs = await list_admin_users()
    return [_to_admin_user(d) for d in docs]


@router.post("", response_model=AdminUser)
async def create_user(
    payload: CreateUserRequest,
    _ctx: RequestContext = Depends(super_admin_guard),
) -> AdminUser:
    await ensure_permission(_ctx, "users", "create")
    roles = _normalize_roles(payload.roles)
    if payload.password_hash:
        if not payload.password_hash.startswith("pbkdf2_sha256$"):
            raise HTTPException(status_code=400, detail="password_hash must be PBKDF2-SHA256")
        user = await create_admin_user_with_hash(
            email=str(payload.email),
            password_hash=payload.password_hash,
            display_name=payload.display_name,
            roles=roles,
            avatar_url=payload.avatar_url,
        )
    elif payload.password:
        user = await create_admin_user(
            email=str(payload.email),
            password=payload.password,
            display_name=payload.display_name,
            roles=roles,
            avatar_url=payload.avatar_url,
        )
    else:
        raise HTTPException(status_code=400, detail="password or password_hash is required")

    return _to_admin_user(user)


@router.get("/{user_id}", response_model=AdminUser)
async def get_user(
    user_id: str,
    _ctx: RequestContext = Depends(admin_guard),
) -> AdminUser:
    await ensure_permission(_ctx, "users", "view")
    user = await get_admin_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_admin_user(user)


@router.put("/{user_id}/roles", response_model=AdminUser)
async def update_roles(
    user_id: str,
    payload: UpdateRolesRequest,
    _ctx: RequestContext = Depends(super_admin_guard),
) -> AdminUser:
    await ensure_permission(_ctx, "users", "assign_role")
    roles = _normalize_roles(payload.roles)
    updated = await update_admin_roles(user_id, roles)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_admin_user(updated)


@router.put("/{user_id}", response_model=AdminUser)
async def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    _ctx: RequestContext = Depends(super_admin_guard),
) -> AdminUser:
    await ensure_permission(_ctx, "users", "edit")
    roles = _normalize_roles(payload.roles) if payload.roles is not None else None
    updated = await update_admin_user(
        user_id,
        display_name=payload.display_name,
        avatar_url=payload.avatar_url,
        roles=roles,
        is_active=payload.is_active,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_admin_user(updated)


@router.post("/{user_id}/change-password")
async def change_password(
    user_id: str,
    payload: ChangePasswordRequest,
    _ctx: RequestContext = Depends(super_admin_guard),
) -> dict:
    await ensure_permission(_ctx, "users", "change_password")
    user = await get_admin_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    stored_hash = user.get("password_hash") or ""
    if not stored_hash or not verify_password(payload.current_password, stored_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if payload.new_password_hash:
        if not payload.new_password_hash.startswith("pbkdf2_sha256$"):
            raise HTTPException(status_code=400, detail="new_password_hash must be PBKDF2-SHA256")
        new_hash = payload.new_password_hash
    elif payload.new_password:
        new_hash = hash_password(payload.new_password)
    else:
        raise HTTPException(status_code=400, detail="new_password or new_password_hash is required")

    ok = await update_admin_password_hash(user_id, new_hash)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update password")
    return {"ok": True}


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    _ctx: RequestContext = Depends(super_admin_guard),
) -> dict:
    await ensure_permission(_ctx, "users", "delete")
    ok = await delete_admin_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}
