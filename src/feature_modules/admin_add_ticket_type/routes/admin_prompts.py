from __future__ import annotations
"""
Admin route to reload prompt cache.

POST /admin/prompts/reload  -> { "ok": true }
"""

from fastapi import APIRouter
from src.services import prompt_loader

router = APIRouter(prefix="/admin/prompts", tags=["admin"])

@router.post("/reload")
async def reload_prompts():
    prompt_loader.reload()
    return {"ok": True}
