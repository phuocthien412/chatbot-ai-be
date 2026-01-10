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

from src.db.mongo import get_db
from src.services.features_registry import get_provider, all_providers, register
from src.services.dynamic_tools import build_tools_for_type_ids

from src.repositories import messages_repo
from src.repositories import debug_sessions_repo, debug_messages_repo
from src.services.intent_tools_picker import pick_tools, build_picker_prompt
from src.services.chat_service import _compose_actor_system_message

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

def _ensure_providers_loaded() -> None:
    try:
        from src.AI_tool_call_modules.tickets.services.provider import provider as tickets_provider
        register(tickets_provider)
    except Exception:
        pass
    try:
        from src.AI_tool_call_modules.info_search.provider import provider as info_search_provider
        register(info_search_provider)
    except Exception:
        pass


def _build_picker_history_from_messages(history: List[Dict[str, Any]]) -> List[dict]:
    msgs: List[dict] = []
    for m in history:
        role = (m.get("role") or "").lower()
        content = (m.get("content") or "")
        if not content:
            continue
        if role not in ("user", "assistant", "tool", "system"):
            role = "user"
        if role == "system" and not content.startswith("TOOL:"):
            continue
        msgs.append({"role": role, "content": content})
    return msgs


async def _build_actor_messages_from_messages(
    history: List[Dict[str, Any]],
    tools_spec: Optional[List[dict]],
    fallback_question: Optional[str],
    provider_addendum: Optional[str],
    language: Optional[str],
) -> List[dict]:
    system_msg = await _compose_actor_system_message(
        tools_spec,
        fallback_question,
        provider_addendum,
        language=language,
    )
    msgs: List[dict] = [{"role": "system", "content": system_msg}]
    for m in history:
        role = (m.get("role") or "").lower()
        content = m.get("content") or ""
        if not content:
            continue
        if role == "system":
            continue
        if role not in ("user", "assistant", "tool"):
            role = "user"
        msgs.append({"role": role, "content": content})
    return msgs


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


@router.post("/session/start")
async def debug_session_start() -> Dict[str, Any]:
    session = await debug_sessions_repo.create_session()
    return {"session_id": session["_id"]}


@router.post("/picker-actor-run")
async def picker_actor_run(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    user_text = payload.get("user_text")
    if not user_text or not isinstance(user_text, str):
        raise HTTPException(400, "user_text is required")

    session = await debug_sessions_repo.create_session()
    session_id = session["_id"]
    await debug_messages_repo.create_user_message(session_id, user_text)

    history = await debug_messages_repo.list_messages(session_id)
    picker_history_msgs = _build_picker_history_from_messages(history)
    pick = await pick_tools(picker_history_msgs)

    capability: Optional[str] = pick.get("capability")
    raw_type_ids = pick.get("type_ids") or []
    type_ids: List[str] = [x for x in raw_type_ids if isinstance(x, str)]
    fallback_question: Optional[str] = pick.get("fallback_question")

    tools_spec: List[Dict[str, Any]] = []
    provider_addendum: Optional[str] = None
    if capability:
        provider = get_provider(capability)
        if provider:
            tools_spec = await provider.tools_spec({
                "session_id": session_id,
                "type_ids": type_ids,
                "target_ids": type_ids,
            })
            try:
                provider_addendum = provider.actor_prompt_addendum()
            except Exception:
                provider_addendum = None

    tool_names = [t.get("function", {}).get("name") for t in tools_spec if isinstance(t, dict)]
    use_fallback = (not tools_spec) and bool(fallback_question)

    actor_messages = await _build_actor_messages_from_messages(
        history,
        tools_spec if tools_spec else None,
        fallback_question if use_fallback else None,
        provider_addendum,
        None,
    )

    return {
        "session_id": session_id,
        "picker": {
            "pick": pick,
            "tools_summary": tool_names,
            "tools_spec": tools_spec,
        },
        "actor": {
            "system_message": (
                actor_messages[0]["content"]
                if actor_messages and actor_messages[0].get("role") == "system"
                else ""
            ),
            "messages": actor_messages,
            "tools_summary": tool_names,
            "tools_spec": tools_spec,
        },
    }


@router.get("/tools-catalog")
async def tools_catalog() -> Dict[str, Any]:
    _ensure_providers_loaded()
    providers = all_providers()

    db = get_db()
    cur = db.ticket_types.find({}, {"_id": 1, "display_name": 1})
    ticket_types = [x async for x in cur]
    type_ids = [str(x["_id"]) for x in ticket_types]
    type_display = {str(x["_id"]): (x.get("display_name") or str(x["_id"])) for x in ticket_types}
    create_tools = await build_tools_for_type_ids(type_ids)

    providers_out: List[Dict[str, Any]] = []
    tools_flat: List[Dict[str, Any]] = []

    for provider in providers:
        tools_spec: List[Dict[str, Any]] = []
        try:
            tools_spec = await provider.tools_spec({"type_ids": [], "target_ids": []})
        except Exception as e:
            tools_spec = [{"error": f"tools_spec failed: {e}"}]

        if getattr(provider, "capability_id", None) == "tickets.create" and create_tools:
            tools_spec = list(tools_spec) + list(create_tools)

        providers_out.append({
            "capability_id": getattr(provider, "capability_id", None),
            "display_name": getattr(provider, "display_name", None),
            "description": getattr(provider, "description", None),
            "tool_count": len([t for t in tools_spec if isinstance(t, dict)]),
            "tools_spec": tools_spec,
        })

        for t in tools_spec:
            if not isinstance(t, dict):
                continue
            fn = t.get("function") if isinstance(t.get("function"), dict) else {}
            name = (fn or {}).get("name") or t.get("name")
            if not name:
                continue
            tool_entry: Dict[str, Any] = {
                "capability_id": getattr(provider, "capability_id", None),
                "provider_display": getattr(provider, "display_name", None),
                "tool_name": name,
                "description": (fn or {}).get("description"),
                "parameters": (fn or {}).get("parameters"),
                "tool_spec": t,
            }
            if isinstance(name, str) and name.startswith("create_ticket__"):
                target_id = name.split("create_ticket__", 1)[1]
                tool_entry["target_id"] = target_id
                tool_entry["target_display"] = type_display.get(target_id)
            tools_flat.append(tool_entry)

    return {
        "providers": providers_out,
        "tools": tools_flat,
        "total_tools": len(tools_flat),
    }
