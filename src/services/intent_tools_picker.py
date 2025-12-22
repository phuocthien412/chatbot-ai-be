from __future__ import annotations
"""
Feature-agnostic, display-name-first tool picker.

- Input: full chat history (list of {role, content})
- Builds a catalog of capabilities and their specs (by display_name) via providers.
- Prompt asks the LLM to pick ONE capability and (optionally) ONE spec by display_name.
- We map the chosen display_name back to the real id to produce target_ids/type_ids for tools.
- Guard: if the LATEST USER message is a list/enumerate question, pick a capability but NO target.

Providers should expose:
    capability_id: str
    (optional) display_name: str           # friendly name for capability
    (optional) get_picker_targets_minimal(db) -> [{"id": str, "display_name": str}, ...]
"""

from typing import Dict, Any, List, Optional, Tuple
import json
import logging
import re

from openai import OpenAI
from src.config import settings
from src.db.mongo import get_db
from src.services.prompt_loader import get_picker_prompt_header
from src.services.features_registry import all_providers

log = logging.getLogger(__name__)
logger = logging.getLogger("uvicorn.error")

# ---------------------- Prompt Template ----------------------

PICKER_SYSTEM = "You are a concise tool-picker. Your output must be in English. Output STRICT JSON only."

PICKER_BODY_TMPL = """{PICKER_HEADER}

You can decide among the following business capabilities (only choose from this list):
{CAPABILITIES_BLOCK}

Each capability may have available specs (by **display name**). If you choose a capability with specs,
select the **one best matching display name** from its list. If no clear task is present, return null.

Specs per capability (by display name):
{TARGETS_BLOCK}

Decision rules:
1) If the LATEST USER message asks to list/show which types are supported, choose a capability but return an EMPTY target_names list.
2) Prefer continuity only if the user is clearly providing fields to complete a ticket.
3) If no ongoing flow and the user asks to create a specific ticket, choose that ticket by its display name.
4) If out-of-scope, return null.
5) At the first user message, return null.

Return STRICT JSON only (no prose/markdown/fences):
{{
  "capability": "<capability_id>" | null,
  "target_names": ["<one_display_name_or_empty>"],    // use display_name value from the list above
  "confidence": 0.0,
  "reason": "≤12 words",
  "fallback_question": "clarifying question"
}}

Conversation transcript (oldest → newest):
{TRANSCRIPT}
"""

# ---------------------- Helpers ----------------------

LIST_INTENT_PATTERNS = [
    r"\bli[eê]t k[êe]\b",                       # liệt kê
    r"\bdanh s[aá]ch\b",                        # danh sách
    r"\b(c[aá]c|to[à]n b[ộo]) (lo[ại]|v[eé])\b",  # các loại / toàn bộ vé
    r"\bnh[ữu]ng v[eé] n[ào]\b",               # những vé nào
    r"\bc[ó] (những )?(v[eé]|lo[ại]) (n[ào]|g[iì]) (h[o]?)?tr[ợo]\b",  # có vé nào hỗ trợ
    r"\b(list|show all|what.*(types|tickets).*(have|support))\b",
]

def _minify_messages(history_msgs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for m in history_msgs or []:
        role = (m.get("role") or "").lower()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role not in ("system", "user", "assistant", "tool"):
            role = "user"
        out.append({"role": role, "content": content})
    return out

def _messages_to_transcript_lines(history_msgs: List[Dict[str, Any]]) -> str:
    return "\n".join([f"{m['role'].upper()}: {m['content']}" for m in _minify_messages(history_msgs)])

def _last_user_text(history_msgs: List[Dict[str, Any]]) -> str:
    for m in reversed(history_msgs or []):
        if (m.get("role") or "").lower() == "user" and isinstance(m.get("content"), str):
            return m["content"]
    return ""

def _is_list_enumeration_intent(history_msgs: List[Dict[str, Any]]) -> bool:
    text = (_last_user_text(history_msgs) or "").lower()
    return any(re.search(p, text) for p in LIST_INTENT_PATTERNS)

async def _collect_catalog() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, str]]]:
    """
    Build catalog and a resolver map:
      catalog entry:
        {
          "capability_id": str,
          "capability_display": str,
          "targets": [{"id": str, "display_name": str}, ...]
        }
      resolver: { capability_id: { display_name_lower: id, ... } }
    """
    catalog: List[Dict[str, Any]] = []
    resolver: Dict[str, Dict[str, str]] = {}
    db = get_db()

    for p in all_providers():
        cap_id = getattr(p, "capability_id", None)
        if not cap_id:
            continue
        cap_disp = getattr(p, "display_name", cap_id)

        targets: List[Dict[str, str]] = []
        get_targets = getattr(p, "get_picker_targets_minimal", None)
        if callable(get_targets):
            try:
                raw = await get_targets(db)
                for t in raw or []:
                    tid = t.get("id") or t.get("_id") or t.get("type_id")
                    name = t.get("display_name") or t.get("name") or str(tid)
                    if tid and name:
                        targets.append({"id": str(tid), "display_name": str(name)})
            except Exception as e:  # pragma: no cover
                log.exception("picker: provider %s get_picker_targets_minimal failed: %s", cap_id, e)

        catalog.append({
            "capability_id": cap_id,
            "capability_display": cap_disp,
            "targets": targets,
        })

        # Build a case-insensitive display_name -> id resolver
        name_map: Dict[str, str] = {}
        for t in targets:
            key = t["display_name"].strip().lower()
            if key:
                name_map[key] = t["id"]
        resolver[cap_id] = name_map

    # Deterministic order
    catalog = sorted(catalog, key=lambda c: c["capability_id"])
    return catalog, resolver

def _format_capabilities_block(catalog: List[Dict[str, Any]]) -> str:
    if not catalog:
        return "- (none)"
    return "\n".join([f"- {c['capability_id']} — \"{c['capability_display']}\"" for c in catalog])

def _format_targets_block(catalog: List[Dict[str, Any]]) -> str:
    if not catalog:
        return "(none)"
    blocks: List[str] = []
    for c in catalog:
        if not c["targets"]:
            blocks.append(f"Capability: {c['capability_id']} — (no specs)")
            continue
        lines = [f"Capability: {c['capability_id']} — specs by display name:"]
        for t in c["targets"]:
            lines.append(f"- {t['display_name']}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)

def _resolve_names_to_ids(capability: Optional[str], target_names: List[str], resolver: Dict[str, Dict[str, str]]) -> List[str]:
    """
    Map model-chosen display names -> true ids (case-insensitive exact match).
    We keep only ONE id (single-target per turn).
    """
    if not capability or not isinstance(target_names, list) or not target_names:
        return []
    name_map = resolver.get(capability) or {}
    out: List[str] = []
    for name in target_names:
        key = (name or "").strip().lower()
        tid = name_map.get(key)
        if tid:
            out.append(tid)
            break
    return out[:1]

# ---------------------- Public: build prompt (for debug) ----------------------

async def build_picker_prompt(history_msgs: List[Dict[str, Any]]) -> Dict[str, Any]:
    header = get_picker_prompt_header() or ""
    catalog, _ = await _collect_catalog()
    transcript = _messages_to_transcript_lines(history_msgs)
    cap_block = _format_capabilities_block(catalog)
    tgt_block = _format_targets_block(catalog)
    prompt = (
        PICKER_BODY_TMPL
        .replace("{PICKER_HEADER}", header)
        .replace("{CAPABILITIES_BLOCK}", cap_block)
        .replace("{TARGETS_BLOCK}", tgt_block)
        .replace("{TRANSCRIPT}", transcript)
    )
    return {
        "prompt": prompt,
        "capabilities_block": cap_block,
        "targets_block": tgt_block,
        "catalog": catalog,
        "picker_input_messages": _minify_messages(history_msgs),
    }

# ---------------------- Public: run picker ----------------------

async def pick_tools(history_msgs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Run the picker LLM and return a generic result + ids resolved from display names.
    Output is back-compat with older code (mirrors target_ids -> type_ids).
    """
    # Build prompt + resolver
    build = await build_picker_prompt(history_msgs)
    prompt: str = build["prompt"]
    _, resolver = await _collect_catalog()  # reuse collection for mapping

    # ---- LLM call (with logging of model + usage) ----
    client = OpenAI(api_key=settings.openai_api_key)
    picker_messages = [
        {"role": "system", "content": PICKER_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    # LOG: picker LLM config
    try:
        logger.info(
            "[PICKER] LLM call → model=%s, msgs=%d",
            settings.openai_model_picker, len(picker_messages)
        )
    except Exception:
        pass

    print(picker_messages)

    resp = client.chat.completions.create(
        model=settings.openai_model_picker,
        messages=picker_messages,
    )

    # LOG: picker usage & tiny preview
    try:
        u = getattr(resp, "usage", None)
        usage_str = (
            f"prompt={getattr(u, 'prompt_tokens', '?')}, "
            f"completion={getattr(u, 'completion_tokens', '?')}, "
            f"total={getattr(u, 'total_tokens', '?')}"
        ) if u else "n/a"
        preview = (resp.choices[0].message.content or "")[:200].replace("\n", " ")
        logger.info("[PICKER] usage: %s | preview: %s", usage_str, preview)
    except Exception:
        pass

    # Parse result
    raw = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except Exception:
        out = {
            "capability": None,
            "target_ids": [],
            "type_ids": [],
            "selected_target_names": [],
            "confidence": 0.0,
            "reason": "parse failed",
            "fallback_question": "Bạn muốn làm gì? (ví dụ: tạo phiếu, tra cứu)",
        }
        log.debug("picker.result(parse-failed): %s", out)
        return out

    # Extract & sanitize
    cap = data.get("capability") or None
    if isinstance(cap, str):
        cap = cap.strip() or None

    target_names = data.get("target_names")
    if not isinstance(target_names, list):
        target_names = []
    elif len(target_names) > 1:
        target_names = target_names[:1]

    # Guard: list/enumerate intent → don't pick a specific target
    if _is_list_enumeration_intent(history_msgs):
        target_names = []

    # Map names -> ids
    target_ids = _resolve_names_to_ids(cap, target_names, resolver)

    out = {
        "capability": cap,
        "target_ids": target_ids,
        "type_ids": list(target_ids),                 # back-compat
        "selected_target_names": target_names,        # for visibility
        "confidence": float(data.get("confidence") or (1.0 if cap else 0.0)),
        "reason": data.get("reason") or "",
        "fallback_question": data.get("fallback_question")
            or "Bạn muốn làm gì? (ví dụ: tạo phiếu, tra cứu)",
    }

    log.debug("picker.result(raw): %s", data)
    log.debug("picker.result(resolved): %s", out)
    return out
