from __future__ import annotations
"""
Actor debug endpoint (bit-for-bit mirror of what the ACTOR sees).

POST /debug/actor-preview-session
Body: { "session_id": "..." }

What this returns:
- The EXACT messages array sent to OpenAI for the actor pass (first item is the single system message).
- The tools_spec provided to the actor (unchanged).
- The picker result that led to those tools.
- A small "openai_payload_preview" to show model/temperature/tool_choice.

Important:
- We DO NOT rebuild or reformat the system message here.
- We reuse the same builder functions from chat_service.py to ensure parity.
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Body, HTTPException

from src.config import settings
from src.services.intent_tools_picker import pick_tools
from src.services.features_registry import get_provider
from src.services.chat_service import (  # reuse EXACT logic from actor flow
    _build_picker_history_messages as cs_build_picker_history_messages,
    _build_actor_messages as cs_build_actor_messages,
)
import json

router = APIRouter(prefix="/debug", tags=["debug"])


def _compact_tool_names(tools_spec: Optional[List[Dict[str, Any]]]) -> List[str]:
    names: List[str] = []
    for t in tools_spec or []:
        fn = (t or {}).get("function") or {}
        name = fn.get("name")
        if isinstance(name, str):
            names.append(name)
    return names


@router.post("/actor-preview-session")
async def actor_preview_session(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    session_id = payload.get("session_id")
    if not session_id or not isinstance(session_id, str):
        raise HTTPException(400, "session_id is required")

    # ---------- PASS 1: run picker against RAW history exactly like chat_service ----------
    picker_history_msgs = await cs_build_picker_history_messages(session_id)
    pick = await pick_tools(picker_history_msgs)

    capability = pick.get("capability")
    raw_type_ids = pick.get("type_ids") or []
    type_ids: List[str] = [x for x in raw_type_ids if isinstance(x, str)]
    fallback_question: Optional[str] = pick.get("fallback_question")

    # Ask provider for tools EXACTLY like chat_service (even when no type_ids)
    tools_spec: List[Dict[str, Any]] = []
    if capability:
        provider = get_provider(capability)
        if provider:
            tools_spec = await provider.tools_spec({
                "session_id": session_id,
                "type_ids": type_ids,
                "target_ids": type_ids,
            })

    # Decide whether to inject fallback (identical logic to chat_service)
    use_fallback = (not tools_spec) and bool(fallback_question)

    # ---------- PASS 2: build the ACTOR messages EXACTLY like chat_service ----------
    actor_messages = await cs_build_actor_messages(
        session_id,
        tools_spec if tools_spec else None,
        fallback_question if use_fallback else None,
    )

    # Pack the same metadata the actor call would use (no extra content added)
    return {
        "picker_phase": {
            "picker_history_variant": "raw_no_banner",
            "pick": pick,
        },
        "actor_receive": {
            # first message should be the single system message produced by chat_service
            "system_message": (
                actor_messages[0]["content"]
                if actor_messages and actor_messages[0].get("role") == "system"
                else ""
            ),
            "fallback_question_injected": use_fallback,
            "openai_payload_preview": {
                "model": settings.openai_model,
                "temperature": 0.2,
                "tool_choice": ("auto" if tools_spec else None),
            },
            "messages": actor_messages,             # ← EXACT messages sent to OpenAI
            "tools_summary": _compact_tool_names(tools_spec),
            "tools_spec": tools_spec,               # ← EXACT tools passed to OpenAI
        },
    }
