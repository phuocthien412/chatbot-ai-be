from __future__ import annotations
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends

from src.security.deps import admin_guard, RequestContext
from src.services.runtime_settings import (
    get_request_timeout_seconds,
    update_request_timeout_seconds,
    get_session_ttl_seconds,
    update_session_ttl_seconds,
    get_session_refresh_leeway_seconds,
    update_session_refresh_leeway_seconds,
)

router = APIRouter(prefix="/admin/settings", tags=["admin.settings"])


class RequestTimeoutResponse(BaseModel):
    request_timeout_seconds: int = Field(..., ge=5, le=600)
    session_ttl_seconds: int = Field(..., ge=300, le=86_400)
    session_refresh_leeway_seconds: int = Field(..., ge=10, le=600)


class RequestTimeoutBody(BaseModel):
    request_timeout_seconds: int = Field(..., ge=5, le=600, description="LLM request timeout (seconds)")
    session_ttl_seconds: int = Field(..., ge=300, le=86_400, description="Session TTL for user tokens (seconds)")
    session_refresh_leeway_seconds: int = Field(..., ge=10, le=600, description="Proactive refresh lead time (seconds)")


@router.get("/request-timeout", response_model=RequestTimeoutResponse)
async def get_request_timeout(_ctx: RequestContext = Depends(admin_guard)) -> RequestTimeoutResponse:
    value = await get_request_timeout_seconds()
    session_ttl = await get_session_ttl_seconds()
    refresh_leeway = await get_session_refresh_leeway_seconds()
    return RequestTimeoutResponse(
        request_timeout_seconds=value,
        session_ttl_seconds=session_ttl,
        session_refresh_leeway_seconds=refresh_leeway,
    )


@router.put("/request-timeout", response_model=RequestTimeoutResponse)
async def put_request_timeout(
    payload: RequestTimeoutBody,
    _ctx: RequestContext = Depends(admin_guard),
) -> RequestTimeoutResponse:
    new_value = await update_request_timeout_seconds(payload.request_timeout_seconds)
    new_ttl = await update_session_ttl_seconds(payload.session_ttl_seconds)
    new_leeway = await update_session_refresh_leeway_seconds(payload.session_refresh_leeway_seconds)
    return RequestTimeoutResponse(
        request_timeout_seconds=new_value,
        session_ttl_seconds=new_ttl,
        session_refresh_leeway_seconds=new_leeway,
    )
