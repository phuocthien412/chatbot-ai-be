from __future__ import annotations
"""Admin authentication endpoints (login/logout).

- POST /admin/auth/login
  Body: { "email": "admin@example.com", "password": "..." }
  -> Issues a JWT with role="admin" and returns basic profile info.

- POST /admin/auth/logout
  -> Stateless logout: always returns {"ok": true} when the token is valid.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr, Field

from src.config import settings
from src.security.jwt import issue_jwt
from src.security.deps import RequestContext, admin_guard
from src.repositories.admin_users_repo import (
    get_admin_by_email,
    verify_password,
    mark_login_success,
)


router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Admin email (case-insensitive)")
    password: str = Field(..., min_length=1, description="Admin password")


class LoginResponse(BaseModel):
    token: str
    role: str
    email: str
    display_name: str
    expires_in: int
    avatar_url: Optional[str] = None


@router.post("/login", response_model=LoginResponse)
async def admin_login(payload: LoginRequest) -> LoginResponse:
    # Look up user
    user = await get_admin_by_email(str(payload.email))
    if not user or not user.get("is_active", True):
        # Avoid leaking which part was wrong
        raise HTTPException(status_code=401, detail="Invalid credentials")

    stored_hash = user.get("password_hash") or ""
    if not stored_hash or not verify_password(payload.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Decide TTL: prefer ADMIN_JWT_TTL_SECONDS, then JWT_TTL_SECONDS, then 1800
    ttl: Optional[int] = None
    try:
        if settings.admin_jwt_ttl_seconds is not None:
            ttl = int(settings.admin_jwt_ttl_seconds)
        elif settings.jwt_ttl_seconds is not None:
            ttl = int(settings.jwt_ttl_seconds)
    except Exception:
        ttl = None

    effective_ttl = ttl if ttl and ttl > 0 else 1800

    sub = f"admin:{user.get('email')}"
    sid = f"admin:{user.get('_id')}"
    tid = "admin"

    token = issue_jwt(
        sub=sub,
        sid=sid,
        tid=tid,
        role="admin",
        ttl_seconds=effective_ttl,
    )

    # Update last_login_at
    await mark_login_success(user.get("_id"))

    return LoginResponse(
        token=token,
        role="admin",
        email=user.get("email"),  # already normalized
        display_name=user.get("display_name") or user.get("email"),
        expires_in=effective_ttl,
        avatar_url=user.get("avatar_url"),
    )


class LogoutResponse(BaseModel):
    ok: bool = True


@router.post("/logout", response_model=LogoutResponse)
async def admin_logout(ctx: RequestContext = Depends(admin_guard)) -> LogoutResponse:  # noqa: ARG001
    """Stateless logout.

    As long as the token is valid and has role="admin", this returns ok=true.
    The frontend should forget the token client-side.
    """
    return LogoutResponse(ok=True)
