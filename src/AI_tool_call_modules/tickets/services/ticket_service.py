from __future__ import annotations
"""
ticket_service.py

handle_create_ticket:
- Validate payload against the ticket type spec (DB)
- Validate 'file' fields: min/max counts, mime/ext, size, belongs to same session
- Insert ticket and return { ok, ticket_id, short_id, type, fields }

Accept shapes for spec.accept:
  - {"mime":[...], "ext":[...]}
  - ["image/jpeg",".pdf","png"]  (list)
  - "image/png, application/pdf" (string)
"""

from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime, timezone
import re

from src.db.mongo import get_db
from src.repositories.files_repo import get_files
from bson import ObjectId



def _short_id(n: int) -> str:
    import string, random
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


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
        parts = [p.strip() for p in re.split(r"[,\s]+", v) if p.strip()]
        return parts
    return []


def _normalize_accept(val) -> Dict[str, List[str]]:
    if isinstance(val, dict):
        mimes = [m.lower() for m in _norm_list(val.get("mime"))]
        exts = [e.lstrip(".").lower() for e in _norm_list(val.get("ext"))]
        return {"mime": mimes, "ext": exts}
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
            exts.append(lit.lstrip("."))
    return {"mime": mimes, "ext": exts}


async def _validate_file_field(session_id: str, key: str, spec_f: Dict[str, Any], value: Any) -> Optional[str]:
    """
    Returns error message if invalid; None if OK.
    value must be a list of file_ids (strings)
    """
    if not isinstance(value, list):
        return f"Field '{key}' must be an array of file IDs."
    min_count = int(spec_f.get("minCount", 1 if spec_f.get("required") else 0))
    max_count = int(spec_f.get("maxCount", 1))
    if max_count < min_count:
        max_count = min_count
    if len(value) < min_count or len(value) > max_count:
        return f"Field '{key}' expects between {min_count} and {max_count} file(s)."

    files = await get_files(value)
    if len(files) != len(value):
        return f"Some file IDs in '{key}' do not exist."

    accept = _normalize_accept(spec_f.get("accept"))
    allowed_mime = set(accept.get("mime", []))
    allowed_ext = set(accept.get("ext", []))
    per_file_max_mb = spec_f.get("perFileMaxMB")
    max_total_mb = spec_f.get("maxSizeMB")
    total_bytes = 0

    for f in files:
        # session ownership
        if str(f.get("session_id")) != session_id:
            return f"File '{f['_id']}' does not belong to this session."

        size = int(f.get("size") or 0)
        total_bytes += size

        # mime/ext checks
        mime = (f.get("mime") or "").lower()
        if allowed_mime:
            # allow exact or wildcard like image/*
            ok_mime = mime in allowed_mime or any(
                (m.endswith("/*") and mime.startswith(m.split("/*")[0] + "/"))
                for m in allowed_mime
            )
            if not ok_mime:
                return f"File '{f['_id']}' has disallowed MIME '{mime}'."

        name = f.get("original_name") or ""
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if allowed_ext and ext and ext not in allowed_ext:
            return f"File '{f['_id']}' has disallowed extension '.{ext}'."

        # per-file size
        if per_file_max_mb is not None and size > int(per_file_max_mb) * 1024 * 1024:
            return f"File '{f['_id']}' exceeds per-file size limit ({per_file_max_mb}MB)."

    if max_total_mb is not None and total_bytes > int(max_total_mb) * 1024 * 1024:
        return f"Total size of '{key}' exceeds {max_total_mb}MB."

    return None


async def handle_create_ticket(session_id: str, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    payload: { "type": "<type_id>", "fields": { ... } }
    """
    db = get_db()
    type_id = payload.get("type")
    fields = payload.get("fields") or payload  # support direct kwargs style

    type_doc = await db.ticket_types.find_one({"_id": type_id})
    if not type_doc:
        return False, {"error": {"code": "TYPE_NOT_FOUND", "message": f"Unknown type '{type_id}'."}}

    spec_fields: List[Dict[str, Any]] = (type_doc.get("spec", {}) or {}).get("fields", []) or []
    spec_by_key = {f["key"]: f for f in spec_fields if f.get("key")}

    # required check
    missing = [k for k, f in spec_by_key.items() if f.get("required") and k not in fields]
    if missing:
        return False, {"error": {"code": "MISSING_FIELDS", "fields": missing}}

    # per-field validation
    for key, val in fields.items():
        f = spec_by_key.get(key)
        if not f:
            return False, {"error": {"code": "UNKNOWN_FIELD", "field": key}}

        ftype = (f.get("type") or "string").lower()
        if ftype == "file":
            err = await _validate_file_field(session_id, key, f, val)
            if err:
                return False, {"error": {"code": "INVALID_FILE", "message": err}}
        elif ftype == "enum":
            enum = f.get("enum") or []
            if not isinstance(val, str) or val not in enum:
                return False, {"error": {"code": "INVALID_ENUM", "field": key, "allowed": enum}}
        elif ftype == "number":
            if not isinstance(val, (int, float)):
                return False, {"error": {"code": "INVALID_NUMBER", "field": key}}
            if "minimum" in f and val < f["minimum"]:
                return False, {"error": {"code": "INVALID_RANGE", "field": key, "min": f["minimum"]}}
            if "maximum" in f and val > f["maximum"]:
                return False, {"error": {"code": "INVALID_RANGE", "field": key, "max": f["maximum"]}}
        else:
            # treat as string-like
            if not isinstance(val, str):
                return False, {"error": {"code": "INVALID_STRING", "field": key}}
            if f.get("minLength") is not None and len(val) < f["minLength"]:
                return False, {"error": {"code": "STRING_TOO_SHORT", "field": key, "minLength": f["minLength"]}}
            if f.get("maxLength") is not None and len(val) > f["maxLength"]:
                return False, {"error": {"code": "STRING_TOO_LONG", "field": key, "maxLength": f["maxLength"]}}
            if f.get("pattern"):
                import re as _re
                if not _re.fullmatch(f["pattern"], val):
                    return False, {"error": {"code": "PATTERN_MISMATCH", "field": key}}

    # Insert ticket
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "type": type_id,
        "fields": fields,
        "session_id": ObjectId(session_id),
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "short_id": _short_id(6),
    }
    res = await db.tickets.insert_one(doc)
    ticket_id = str(res.inserted_id)

    return True, {
        "ticket_id": ticket_id,
        "short_id": doc["short_id"],
        "type": type_id,
        "fields": fields,
        "status": "open",
        "created_at": now,
    }
