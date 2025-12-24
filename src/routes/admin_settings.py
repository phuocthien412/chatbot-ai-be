from __future__ import annotations
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends

from src.security.deps import admin_guard, RequestContext
from src.services.runtime_settings import (
    get_request_timeout_seconds,
    update_request_timeout_seconds,
)

router = APIRouter(prefix="/admin/settings", tags=["admin.settings"])


class RequestTimeoutResponse(BaseModel):
    request_timeout_seconds: int = Field(..., ge=5, le=600)


class RequestTimeoutBody(BaseModel):
    request_timeout_seconds: int = Field(..., ge=5, le=600, description="LLM request timeout (seconds)")


@router.get("/request-timeout", response_model=RequestTimeoutResponse)
async def get_request_timeout(_ctx: RequestContext = Depends(admin_guard)) -> RequestTimeoutResponse:
    value = await get_request_timeout_seconds()
    return RequestTimeoutResponse(request_timeout_seconds=value)


@router.put("/request-timeout", response_model=RequestTimeoutResponse)
async def put_request_timeout(
    payload: RequestTimeoutBody,
    _ctx: RequestContext = Depends(admin_guard),
) -> RequestTimeoutResponse:
    new_value = await update_request_timeout_seconds(payload.request_timeout_seconds)
    return RequestTimeoutResponse(request_timeout_seconds=new_value)
