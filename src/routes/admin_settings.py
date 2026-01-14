from __future__ import annotations
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends

from src.security.deps import admin_guard, RequestContext
from src.security.permissions import ensure_permission
from src.services.runtime_settings import (
    get_request_timeout_seconds,
    update_request_timeout_seconds,
    get_session_ttl_seconds,
    update_session_ttl_seconds,
    get_session_refresh_leeway_seconds,
    update_session_refresh_leeway_seconds,
    get_ai_config,
    update_ai_config,
)

router = APIRouter(prefix="/admin/settings", tags=["admin.settings"])


class RequestTimeoutResponse(BaseModel):
    request_timeout_seconds: int = Field(..., ge=5, le=600)
    session_ttl_seconds: int = Field(..., ge=60, le=86_400)
    session_refresh_leeway_seconds: int = Field(..., ge=10, le=600)


class RequestTimeoutBody(BaseModel):
    request_timeout_seconds: int = Field(..., ge=5, le=600, description="LLM request timeout (seconds)")
    session_ttl_seconds: int = Field(..., ge=60, le=86_400, description="Session TTL for user tokens (seconds)")
    session_refresh_leeway_seconds: int = Field(..., ge=10, le=600, description="Proactive refresh lead time (seconds)")


class AiConfigResponse(BaseModel):
    openai_model: str
    openai_model_picker: str
    openai_model_actor: str
    openai_model_ticket_gen: str
    openai_model_rag: str
    openai_model_vision: str
    openai_model_tts: str
    openai_tts_voice: str
    tts_default_format: str
    prompt_char_budget: int = Field(..., ge=1000, le=500_000)
    single_message_char_limit: int = Field(..., ge=1000, le=100_000)
    request_timeout_seconds: int = Field(..., ge=5, le=600)


class AiConfigBody(BaseModel):
    openai_model: str | None = None
    openai_model_picker: str | None = None
    openai_model_actor: str | None = None
    openai_model_ticket_gen: str | None = None
    openai_model_rag: str | None = None
    openai_model_vision: str | None = None
    openai_model_tts: str | None = None
    openai_tts_voice: str | None = None
    tts_default_format: str | None = None
    prompt_char_budget: int | None = Field(default=None, ge=1000, le=500_000)
    single_message_char_limit: int | None = Field(default=None, ge=1000, le=100_000)
    request_timeout_seconds: int | None = Field(default=None, ge=5, le=600)


@router.get("/request-timeout", response_model=RequestTimeoutResponse)
async def get_request_timeout(ctx: RequestContext = Depends(admin_guard)) -> RequestTimeoutResponse:
    await ensure_permission(ctx, "settings", "view")
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
    ctx: RequestContext = Depends(admin_guard),
) -> RequestTimeoutResponse:
    await ensure_permission(ctx, "settings", "edit")
    new_value = await update_request_timeout_seconds(payload.request_timeout_seconds)
    new_ttl = await update_session_ttl_seconds(payload.session_ttl_seconds)
    new_leeway = await update_session_refresh_leeway_seconds(payload.session_refresh_leeway_seconds)
    return RequestTimeoutResponse(
        request_timeout_seconds=new_value,
        session_ttl_seconds=new_ttl,
        session_refresh_leeway_seconds=new_leeway,
    )


@router.get("/ai-config", response_model=AiConfigResponse)
async def get_ai_settings(ctx: RequestContext = Depends(admin_guard)) -> AiConfigResponse:
    await ensure_permission(ctx, "settings", "view")
    data = await get_ai_config()
    return AiConfigResponse(**data)


@router.put("/ai-config", response_model=AiConfigResponse)
async def put_ai_settings(
    payload: AiConfigBody,
    ctx: RequestContext = Depends(admin_guard),
) -> AiConfigResponse:
    await ensure_permission(ctx, "settings", "edit")
    data = await update_ai_config(payload.model_dump(exclude_none=True))
    return AiConfigResponse(**data)
