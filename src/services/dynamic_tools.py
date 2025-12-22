from __future__ import annotations
"""
dynamic_tools.py

Builds OpenAI tool schemas from selected ticket type IDs.
Supports field types: string, enum, number, phone, email, file.

For 'file' fields we emit:
  - type: array of strings
  - minItems / maxItems from spec (defaults)
  - description includes short upload hint and allowed types

Now robust to 'accept' being:
  - dict: {"mime":[...], "ext":[...]}
  - list/str: treated as mime list (".pdf" entries become ext)
"""

from typing import List, Dict, Any
import re
from src.db.mongo import get_db


def _norm_list(v) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        out: List[str] = []
        for item in v:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    out.append(s)
        return out
    if isinstance(v, str):
        # split by comma or whitespace
        parts = [p.strip() for p in re.split(r"[,\s]+", v) if p.strip()]
        return parts
    return []


def _normalize_accept(val) -> Dict[str, List[str]]:
    """
    Accept flexible shapes and normalize to:
    { "mime": [...], "ext": [...] }
    """
    if isinstance(val, dict):
        mimes = _norm_list(val.get("mime"))
        exts = [e.lstrip(".").lower() for e in _norm_list(val.get("ext"))]
        mimes = [m.lower() for m in mimes]
        return {"mime": mimes, "ext": exts}

    # list/str → treat as mime list; ".pdf" entries become ext
    items = _norm_list(val)
    mimes: List[str] = []
    exts: List[str] = []
    for it in items:
        lit = it.lower()
        if lit.startswith("."):
            exts.append(lit.lstrip("."))
        elif "/" in lit or lit.endswith("/*"):
            mimes.append(lit)
        else:
            # could be an extension without a leading dot (e.g., "pdf")
            exts.append(lit.lstrip("."))
    return {"mime": mimes, "ext": exts}


def _field_to_schema(f: Dict[str, Any]) -> Dict[str, Any]:
    ftype = (f.get("type") or "string").lower()

    if ftype == "enum":
        return {
            "type": "string",
            "enum": list(f.get("enum") or []),
            "description": f.get("description") or f.get("label") or "",
        }

    if ftype == "number":
        s: Dict[str, Any] = {"type": "number"}
        if "minimum" in f:
            s["minimum"] = f["minimum"]
        if "maximum" in f:
            s["maximum"] = f["maximum"]
        if f.get("description"):
            s["description"] = f["description"]
        return s

    if ftype in ("phone", "email"):
        s: Dict[str, Any] = {"type": "string"}
        if ftype == "phone" and f.get("pattern"):
            s["pattern"] = f["pattern"]
        if ftype == "email":
            s["format"] = "email"
        if f.get("minLength") is not None:
            s["minLength"] = f["minLength"]
        if f.get("maxLength") is not None:
            s["maxLength"] = f["maxLength"]
        if f.get("description"):
            s["description"] = f["description"]
        return s

    if ftype == "file":
        min_count = int(f.get("minCount", 1 if f.get("required") else 0))
        max_count = int(f.get("maxCount", 1))
        if max_count < min_count:
            max_count = min_count
        accept = _normalize_accept(f.get("accept"))
        mimes = accept.get("mime", [])
        exts = accept.get("ext", [])

        hint_parts: List[str] = []
        if mimes:
            hint_parts.append("MIME: " + ",".join(mimes))
        if exts:
            hint_parts.append("ext: " + ",".join(exts))
        counts = f"min={min_count}, max={max_count}"
        base_desc = f.get("description") or f.get("label") or "Upload files, then pass file IDs."
        desc = f"{base_desc} (Use /files/upload; pass file IDs as an array. {counts}. {'; '.join(hint_parts)})".strip()

        return {
            "type": "array",
            "items": {"type": "string"},
            "minItems": min_count,
            "maxItems": max_count,
            "description": desc,
        }

    # default: string-like
    s = {"type": "string"}
    if f.get("minLength") is not None:
        s["minLength"] = f["minLength"]
    if f.get("maxLength") is not None:
        s["maxLength"] = f["maxLength"]
    if f.get("pattern"):
        s["pattern"] = f["pattern"]
    if f.get("description"):
        s["description"] = f["description"]
    return s


def _build_tool_for_type(doc: Dict[str, Any]) -> Dict[str, Any]:
    type_id = doc["_id"]
    display = doc.get("display_name") or type_id
    fields = (doc.get("spec", {}) or {}).get("fields", []) or []

    props: Dict[str, Any] = {}
    required: List[str] = []
    for f in fields:
        key = f.get("key")
        if not key:
            continue
        props[key] = _field_to_schema(f)
        if f.get("required"):
            required.append(key)

    params: Dict[str, Any] = {
        "type": "object",
        "properties": props,
        "additionalProperties": False,
    }
    if required:
        params["required"] = required

    description = (
        f"Create ticket for type '{display}'. Ask the user for any missing required field (including files) before calling."
    )

    return {
        "type": "function",
        "function": {
            "name": f"create_ticket__{type_id}",
            "description": description,
            "parameters": params,
        },
    }


async def build_tools_for_type_ids(type_ids: List[str]) -> List[Dict[str, Any]]:
    if not type_ids:
        return []
    db = get_db()
    cur = db.ticket_types.find({"_id": {"$in": type_ids}})
    docs = [x async for x in cur]
    tools: List[Dict[str, Any]] = []
    for d in docs:
        tools.append(_build_tool_for_type(d))
    return tools
