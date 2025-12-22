from __future__ import annotations
"""
chat_service.py

Two-pass flow:
- Pass 1 (tool-picker): choose a minimal tools_spec for this turn (0..N tools) using the FULL history list.
- Pass 2 (actor): normal chat call with a single, well-structured system prompt + chosen tools; handle tool calls.

This version:
- Picker sees RAW conversation (no actor banner) to avoid bias.
- Actor gets exactly ONE system message composed as:
  [This turn: Tools] → [Business/Profile header (includes your core rules)] → [Provider addendum (if any)] → [Capabilities banner (reference)] → [optional fallback]
- History 'system' breadcrumbs like "TOOL:..." are filtered out from the actor view.
- We ask provider.tools_spec EVEN IF no type_ids, so discovery tools (e.g., tickets__list_types) can be exposed.

Adds logging:
- Logs the LLM model and token usage for both actor calls (CALL#1 and CALL#2).

NEW (KB-only behavior):
- If a chosen provider exposes `force_tool_name`, we:
  1) Insert its `actor_prompt_addendum()` into the system prompt (KB-only policy).
  2) Force the LLM tool choice to that function (deterministic tool call).
  3) If the model still returns NO tool_calls, we SYNTHESIZE a tool call for this turn,
     invoking `provider.handle_tool_call` with {"query": <last user message>} and then
     proceed with CALL#2 so the LLM can write a natural answer based on the tool result.
- Ticket flow and other capabilities are unaffected.
"""

from typing import List, Tuple, Dict, Any, Optional
import asyncio
import json
import logging
import re

from openai import OpenAI
from src.services.picker_hints import collect_picker_hints
from src.config import settings
from src.repositories import sessions_repo, messages_repo
from src.repositories.messages_repo import create_system_message
from src.services.features_registry import get_provider, all_providers
from src.services.intent_tools_picker import pick_tools
from src.services.capabilities_banner import get_capabilities_banner_text
from src.services.suggestions_extractor import extract_suggestions
from src.services.prompt_loader import get_actor_prompt_header
from src.services.events import broadcast_event

logger = logging.getLogger("uvicorn.error")

# ---------------------------- helpers ----------------------------

def _require_actor_model() -> str:
    model = getattr(settings, "openai_model_actor", None)
    if not model:
        # Explicit error so misconfig surfaces fast
        raise RuntimeError("ACTOR MODEL MISSING")
    return model

def _summarize_tools_for_system(tools_spec: Optional[List[dict]]) -> str:
    """
    Produce a short human-readable list of tools available this turn.
    Tries to extract a display label from the description when present.
    """
    if not tools_spec:
        return "- (No tools available this turn)"

    items = []
    pat = re.compile(r"type '([^']+)'", re.IGNORECASE)
    for t in tools_spec:
        fn = (t or {}).get("function") or {}
        name = fn.get("name") or "unknown"
        desc = (fn.get("description") or "").strip()
        label = None
        m = pat.search(desc)
        if m:
            label = m.group(1)
        if label:
            items.append(f"- {name} — “{label}”")
        else:
            items.append(f"- {name}")
    return "\n".join(items)

async def _compose_actor_system_message(
    turn_tools_spec: Optional[List[dict]] = None,
    fallback_question: Optional[str] = None,
    provider_addendum: Optional[str] = None,
) -> str:
    """
    Build a SINGLE system message in this order:
      1) This turn: Tools (top, so the model grounds on capabilities for THIS turn)
      2) Business/Profile header (your core rules live here)
      3) Provider addendum (e.g., KB-only policy with few-shot)
      4) Capabilities banner (reference at the bottom)
      5) Optional fallback question (appended at end)
    """
    # (1) This turn’s tools
    tools_block = "## Tools available this turn\n" + _summarize_tools_for_system(turn_tools_spec)

    # (2) Business/Profile header (already contains your core rules)
    business_header = (get_actor_prompt_header() or "").strip()
    business_block = business_header if business_header else ""

    # (3) Provider addendum (KB-only rules, etc.)
    provider_block = (provider_addendum or "").strip()

    # (4) Capabilities banner (reference at the bottom)
    banner = await get_capabilities_banner_text()
    try:
        # Merge feature providers' one-liners
        provider_chunks = [p.capabilities_banner_chunk().strip() for p in all_providers()]
        provider_chunks = [c for c in provider_chunks if c]
        if provider_chunks:
            banner = f"{banner}\n" + " ; ".join(provider_chunks)
    except Exception:
        pass
    banner_block = "## Capabilities reference\n" + banner.strip() if banner else ""

    # (5) Optional fallback (inline in same system message)
    fallback_line = f"\n\nSuggested disambiguation question: {fallback_question}" if fallback_question else ""

    parts = [tools_block]
    if business_block:
        parts.append(business_block)
    if provider_block:
        parts.append(provider_block)
    if banner_block:
        parts.append(banner_block)

    sys_msg = "\n\n".join(parts).strip() + fallback_line
    # print(sys_msg)
    return sys_msg

async def _build_actor_messages(
    session_id: str,
    tools_spec: Optional[List[dict]],
    fallback_question: Optional[str],
    provider_addendum: Optional[str],
) -> List[dict]:
    """
    Exactly what the ACTOR uses:
      - one system message (from _compose_actor_system_message)
      - full history, but WITHOUT old system breadcrumbs ("TOOL:...") and without other system lines.
    """
    history = await messages_repo.list_messages(session_id)

    # single well-structured system message
    system_msg = await _compose_actor_system_message(tools_spec, fallback_question, provider_addendum)

    msgs: List[dict] = [{"role": "system", "content": system_msg}]

    # append history; drop noisy system breadcrumbs and any other prior system lines
    for m in history:
        role = (m.get("role") or "").lower()
        content = m.get("content") or ""
        if not content:
            continue
        if role == "system":
            # drop internal breadcrumbs like TOOL:... and any leftover systems to avoid clutter
            continue
        if role not in ("user", "assistant", "tool"):
            role = "user"
        msgs.append({"role": role, "content": content})
    return msgs

# Picker should see only raw conversation (no actor system banners) to reduce bias.
async def _build_picker_history_messages(session_id: str) -> List[dict]:
    history = await messages_repo.list_messages(session_id)
    msgs: List[dict] = []
    for m in history:
        role = (m.get("role") or "").lower()
        content = (m.get("content") or "")
        if not content:
            continue
        if role not in ("user", "assistant", "tool", "system"):
            role = "user"
        # keep only TOOL breadcrumbs if any; skip actor banners
        if role == "system" and not content.startswith("TOOL:"):
            continue
        msgs.append({"role": role, "content": content})
    return msgs

def _call_openai_sync(
    model: str,
    messages: List[dict],
    timeout: int,
    tools: Optional[List[dict]] = None,
    tool_choice: Optional[Any] = None,  # Accept dict or string for forcing
):
    client = OpenAI(api_key=settings.openai_api_key)
    return client.chat.completions.create(
        model=model,
        messages=messages,
        timeout=timeout,
        tools=tools,
        tool_choice=tool_choice,
    )

def _tool_names_list(tools_spec: Optional[List[dict]]) -> List[str]:
    names: List[str] = []
    for t in tools_spec or []:
        fn = (t or {}).get("function") or {}
        n = fn.get("name")
        if isinstance(n, str):
            names.append(n)
    return names

async def _create_ticket_in_backend(session_id: str, type_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    from AI_tool_call_modules.tickets.services.ticket_service import handle_create_ticket
    ok, result = await handle_create_ticket(session_id, {"type": type_id, "fields": fields})
    if ok:
        return {"ok": True, **result}
    return {"ok": False, "error": result.get("error") or {"code": "CREATE_FAILED"}}

def _tool_name_to_type_id(tool_name: str) -> Optional[str]:
    if not tool_name.startswith("create_ticket__"):
        return None
    return tool_name.split("create_ticket__", 1)[1] or None

# ---------------------------- main turn ----------------------------

async def chat_turn(session_id: str, user_text: str) -> Tuple[str, str, List[str]]:
    """
    Returns: (assistant_message_id, clean_reply_text, suggestions_list)
    """
    # Ensure session & persist user message
    session = await sessions_repo.get_session(session_id)
    if not session:
        session = await sessions_repo.create_session()
        session_id = session["_id"]

    user_doc = await messages_repo.create_user_message(session_id, user_text)
    # Broadcast user message immediately for realtime admin view
    try:
        await broadcast_event({"type": "message.created", "data": user_doc})
        await broadcast_event({
            "type": "conversation.updated",
            "data": {
                "session_id": session_id,
                "last_message_at": user_doc.get("created_at"),
                "last_sender": "user",
            },
        })
    except Exception:
        pass

    # ---------- PASS 1: picker reads RAW full history ----------
    picker_history_msgs = await _build_picker_history_messages(session_id)

    # Hints pre-scoring (MVP)
    hint = collect_picker_hints({"history": picker_history_msgs})
    preferred_cap = hint.get("top_capability")

    pick = await pick_tools(picker_history_msgs)
    capability = pick.get("capability") or preferred_cap

    raw_type_ids = pick.get("type_ids") or []
    type_ids: List[str] = []
    for item in raw_type_ids:
        if isinstance(item, str):
            type_ids.append(item)
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            type_ids.append(item["id"])

    fallback_question = pick.get("fallback_question")

    tools_spec: List[Dict[str, Any]] = []
    provider_addendum: Optional[str] = None
    force_tool_name: Optional[str] = None

    provider = get_provider(capability) if capability else None
    if provider:
        # Ask provider for tools EVEN when no type_ids (discovery tools can be exposed)
        tools_spec = await provider.tools_spec({
            "session_id": session_id,
            "type_ids": type_ids,
            "target_ids": type_ids,
        })
        # Read provider addendum (KB-only policy etc.)
        try:
            provider_addendum = provider.actor_prompt_addendum()  # may be None
        except Exception:
            provider_addendum = None
        # Force tool name if the provider wants deterministic tool-calls
        force_tool_name = getattr(provider, "force_tool_name", None)
        logger.info(f"[PICKER] capability={capability} types={type_ids} conf={pick.get('confidence')}")
    else:
        logger.info(f"[PICKER] no capability selected (conf={pick.get('confidence')})")

    # ---------- PASS 2: actor completion w/ chosen tools ----------
    openai_msgs = await _build_actor_messages(
        session_id,
        tools_spec=tools_spec if tools_spec else None,
        fallback_question=fallback_question if not tools_spec else None,
        provider_addendum=provider_addendum,
    )
    actor_model = _require_actor_model()

    # Determine tool_choice (auto vs forced)
    tool_names = _tool_names_list(tools_spec)
    tool_choice: Any = None
    tool_choice_log = "none"
    if tools_spec:
        if force_tool_name and force_tool_name in tool_names:
            tool_choice = {"type": "function", "function": {"name": force_tool_name}}
            tool_choice_log = f"force:{force_tool_name}"
        else:
            tool_choice = "auto"
            tool_choice_log = "auto"

    # LOG: actor CALL#1 (pre-call)
    try:
        logger.info(
            "[ACTOR:CALL1] LLM model=%s | tool_choice=%s | tools=%d %s",
            actor_model,
            tool_choice_log,
            len(tool_names),
            f"| {tool_names}" if tool_names else ""
        )
    except Exception:
        pass

    first = await asyncio.to_thread(
        _call_openai_sync,
        actor_model,
        openai_msgs,
        settings.request_timeout_seconds,
        tools=tools_spec if tools_spec else None,
        tool_choice=tool_choice,
    )

    # LOG: actor CALL#1 usage
    try:
        u = getattr(first, "usage", None)
        usage_str = (
            f"prompt={getattr(u, 'prompt_tokens', '?')}, "
            f"completion={getattr(u, 'completion_tokens', '?')}, "
            f"total={getattr(u, 'total_tokens', '?')}"
        ) if u else "n/a"
        logger.info("[ACTOR:CALL1] usage: %s", usage_str)
    except Exception:
        pass

    choice = first.choices[0]
    msg = choice.message
    tool_calls = getattr(msg, "tool_calls", None)

    # If no tool call but provider requires one (KB-only), synthesize a tool call using the last user text.
    synthesized_tc = None
    if not tool_calls and provider and force_tool_name and (force_tool_name in tool_names):
        try:
            # Construct args for a typical RAG tool signature
            synth_args = {"query": user_text}
            logger.info(f"[TOOL CALL - SYNTH] {force_tool_name} args={synth_args}")
            result = await provider.handle_tool_call(session_id, force_tool_name, synth_args)
            logger.info(f"[TOOL RESULT - SYNTH] {result}")

            # Build synthetic tool call id for continuity into CALL#2
            synthesized_tc = {
                "id": "forced_1",
                "type": "function",
                "function": {"name": force_tool_name, "arguments": json.dumps(synth_args, ensure_ascii=False)}
            }

            # Prepare follow-up messages as if the LLM called the tool
            follow_messages = openai_msgs + [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [synthesized_tc],
                },
                {
                    "role": "tool",
                    "tool_call_id": "forced_1",
                    "content": json.dumps(result, ensure_ascii=False),
                },
            ]

            # LOG: actor CALL#2 (pre-call)
            try:
                logger.info(
                    "[ACTOR:CALL2] LLM model=%s | tool_choice=none | echo synthesized tool result",
                    actor_model
                )
            except Exception:
                pass

            second = await asyncio.to_thread(
                _call_openai_sync,
                actor_model,
                follow_messages,
                settings.request_timeout_seconds,
                tools=tools_spec if tools_spec else None,
                tool_choice="none" if tools_spec else None,
            )

            # LOG: actor CALL#2 usage
            try:
                u2 = getattr(second, "usage", None)
                usage_str2 = (
                    f"prompt={getattr(u2, 'prompt_tokens', '?')}, "
                    f"completion={getattr(u2, 'completion_tokens', '?')}, "
                    f"total={getattr(u2, 'total_tokens', '?')}"
                ) if u2 else "n/a"
                logger.info("[ACTOR:CALL2] usage: %s", usage_str2)
            except Exception:
                pass

            raw_text = (second.choices[0].message.content or "").strip()
            clean_text, suggestions = extract_suggestions(raw_text)
            a_doc = await messages_repo.create_assistant_message(session_id, clean_text)
            await sessions_repo.touch_session(session_id)
            return a_doc["_id"], clean_text, suggestions

        except Exception as e:
            logger.exception(f"[SYNTH_TOOL_CALL_ERROR] {e}")
            # If synthetic path fails, fall back to plain text path below

    # No tool call => assistant text (summary/clarifier) + suggestions tag
    if not tool_calls:
        raw_text = msg.content or ""
        clean_text, suggestions = extract_suggestions(raw_text)
        a_doc = await messages_repo.create_assistant_message(session_id, clean_text)
        await sessions_repo.touch_session(session_id)
        return a_doc["_id"], clean_text, suggestions

    # Handle the first tool call (MVP)
    tc = tool_calls[0]
    tool_name = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
    except Exception:
        args = {}

    logger.info(f"[TOOL CALL] {tool_name} args={args}")

    provider = get_provider(capability)
    if provider:
        result = await provider.handle_tool_call(session_id, tool_name, args)
    else:
        result = {"ok": False, "error": {"code": "UNKNOWN_CAPABILITY"}}
    logger.info(f"[TOOL RESULT] {result}")

    # Second completion: natural response, forbid more tool calls this turn
    follow_messages = openai_msgs + [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": json.dumps(args, ensure_ascii=False)},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, ensure_ascii=False),
        },
    ]

    # LOG: actor CALL#2 (pre-call)
    try:
        logger.info(
            "[ACTOR:CALL2] LLM model=%s | tool_choice=none | echo tool result",
            actor_model
        )
    except Exception:
        pass

    second = await asyncio.to_thread(
        _call_openai_sync,
        actor_model,
        follow_messages,
        settings.request_timeout_seconds,
        tools=tools_spec if tools_spec else None,
        tool_choice="none" if tools_spec else None,
    )

    # LOG: actor CALL#2 usage
    try:
        u2 = getattr(second, "usage", None)
        usage_str2 = (
            f"prompt={getattr(u2, 'prompt_tokens', '?')}, "
            f"completion={getattr(u2, 'completion_tokens', '?')}, "
            f"total={getattr(u2, 'total_tokens', '?')}"
        ) if u2 else "n/a"
        logger.info("[ACTOR:CALL2] usage: %s", usage_str2)
    except Exception:
        pass

    raw_text = (second.choices[0].message.content or "").strip()
    clean_text, suggestions = extract_suggestions(raw_text)

    # Breadcrumb on success (ticket creation remains unchanged)
    if result.get("ok"):
        try:
            short_id = result.get("short_id")
            breadcrumb_type = result.get("type") or _tool_name_to_type_id(tool_name) or "unknown"
            await create_system_message(
                session_id,
                f"TOOL:create_ticket short_id={short_id} type={breadcrumb_type}"
            )
        except Exception:
            pass

    a_doc = await messages_repo.create_assistant_message(session_id, clean_text)
    await sessions_repo.touch_session(session_id)
    return a_doc["_id"], clean_text, suggestions
