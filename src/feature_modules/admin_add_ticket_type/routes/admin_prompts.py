from __future__ import annotations
"""
Admin route to reload prompt cache.

POST /admin/prompts/reload  -> { "ok": true }
"""

from fastapi import APIRouter, Depends
from src.services import prompt_loader
from src.repositories import sessions_repo
from src.security.deps import RequestContext, admin_guard
from src.security.permissions import ensure_permission

router = APIRouter(prefix="/admin/prompts", tags=["admin"])

@router.post("/reload")
async def reload_prompts(ctx: RequestContext = Depends(admin_guard)):
    await ensure_permission(ctx, "prompts", "reload")
    prompt_loader.reload()
    # Mark all conversations as ended to reflect reset
    try:
        await sessions_repo.mark_all_status("ended")
    except Exception:
        pass
    return {"ok": True, "status": "ended_all"}
