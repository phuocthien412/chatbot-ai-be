from __future__ import annotations
"""
Debug endpoints for the picker.

- POST /debug/picker-preview
  Body: { "user_text": "..." }
  -> Builds a 1-message history and returns:
     {
       picker_input_messages: [ {role, content}, ... ],
       picker_prompt_preview: "<the exact prompt string>",
       picker_catalog_preview: [
         { capability_id, capability_display, targets: [{display_name}] }
       ],
       pick: { capability, target_ids, type_ids, selected_target_names, ... },
       actor_input_ctx: { type_ids, target_ids },
       tools_summary: ["create_ticket__...", ...],
       tools_spec: [ {type:"function", function:{name, description, parameters}}, ... ]
     }

- POST /debug/picker-preview-session
  Body: { "session_id": "..." }
  -> Fetches the FULL session history and does the same.
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Body, HTTPException

from src.repositories import messages_repo
from src.services.intent_tools_picker import pick_tools, build_picker_prompt
from src.services.features_registry import get_provider

router = APIRouter(prefix="/debug", tags=["debug"])


async def _preview_for_history(history_msgs: List[Dict[str, Any]]) -> Dict[str, Any]:
    # 1) What picker actually sees
    built = await build_picker_prompt(history_msgs)
    picker_input_messages = built["picker_input_messages"]
    picker_prompt_preview = built["prompt"]
    picker_catalog_preview = built["catalog"]

    # 2) Run picker
    pick = await pick_tools(history_msgs)

    capability: Optional[str] = pick.get("capability")
    target_ids: List[str] = pick.get("target_ids") or []
    type_ids: List[str] = pick.get("type_ids") or list(target_ids)

    # 3) What we send to the actor/provider
    actor_input_ctx: Dict[str, Any] = {"type_ids": type_ids, "target_ids": target_ids}

    tools_spec: List[Dict[str, Any]] = []
    names: List[str] = []
    if capability:
        provider = get_provider(capability)
        if provider:
            try:
                tools_spec = await provider.tools_spec(actor_input_ctx)
                names = [t.get("function", {}).get("name")
                         for t in tools_spec if isinstance(t, dict)]
            except Exception as e:
                tools_spec = [{"error": f"tools_spec failed: {e}"}]

    return {
        "picker_input_messages": picker_input_messages,
        "picker_prompt_preview": picker_prompt_preview,
        "picker_catalog_preview": [
            {
                "capability_id": c["capability_id"],
                "capability_display": c["capability_display"],
                "targets_count": len(c.get("targets") or []),
                "targets": [{"display_name": t["display_name"]} for t in (c.get("targets") or [])],
            } for c in picker_catalog_preview
        ],
        "pick": pick,
        "actor_input_ctx": actor_input_ctx,
        "tools_summary": names,
        "tools_spec": tools_spec,
    }


@router.post("/picker-preview")
async def picker_preview(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    user_text = payload.get("user_text")
    if not user_text or not isinstance(user_text, str):
        raise HTTPException(400, "user_text is required")
    history_msgs = [{"role": "user", "content": user_text}]
    return await _preview_for_history(history_msgs)


@router.post("/picker-preview-session")
async def picker_preview_session(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    session_id = payload.get("session_id")
    if not session_id or not isinstance(session_id, str):
        raise HTTPException(400, "session_id is required")

    history = await messages_repo.list_messages(session_id)
    if not history:
        raise HTTPException(404, "No messages found in this session")

    return await _preview_for_history(history)
