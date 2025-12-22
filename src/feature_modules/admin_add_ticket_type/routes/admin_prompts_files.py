from __future__ import annotations
"""
Admin API for editing business prompt files (file-backed, safe, simple).

Endpoints
- GET  /admin/prompts/files
- GET  /admin/prompts/file/{name}            (name ∈ {"profile","policies","glossary"})
- PUT  /admin/prompts/file/{name}            body: {"content": "…", "note": "optional"}
- POST /admin/prompts/reload                 (already exists elsewhere; we call loader.reload() here too)
- POST /admin/prompts/preview                -> {"actor_preview","picker_preview"}
- POST /admin/prompts/rollback               body: {"name":"profile","backup":"profile-2025-09-26T10_12_00Z.md"}

Auth (minimal, optional):
- If env ADMIN_KEY is set, require header "X-Admin-Key: <ADMIN_KEY>".
- If ADMIN_KEY is NOT set, allow requests BUT log a loud warning.
- Additionally, we reject non-local clients when ADMIN_KEY is absent.

Safety:
- Whitelist file names (profile|policies|glossary) ONLY.
- Max content size: 5 KB.
- Enforce UTF-8 text.
- Write versioned backup into prompts/.versions/{name}-{ISO}.md before overwrite.
- Never expose or edit system cores (system/actor.core.md, system/picker.core.md).
"""

import os
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from src.services import prompt_loader
from src.services.capabilities_banner import get_capabilities_banner_text
from src.services.prompt_loader import get_actor_prompt_header, get_picker_prompt_header

router = APIRouter(prefix="/admin/prompts", tags=["admin"])

# ---------- Config ----------
PROMPTS_ROOT = os.environ.get("PROMPTS_ROOT", os.path.join(os.getcwd(), "prompts"))
BUSINESS_DIR = os.path.join(PROMPTS_ROOT, "business")
SYSTEM_DIR = os.path.join(PROMPTS_ROOT, "system")
VERSIONS_DIR = os.path.join(PROMPTS_ROOT, ".versions")

ALLOWED_NAMES = {"profile", "policies", "glossary"}
MAX_BYTES = 5 * 1024  # 5 KB
ADMIN_KEY = os.environ.get("ADMIN_KEY")  # optional

# ---------- Helpers ----------
def _ensure_dirs() -> None:
    os.makedirs(BUSINESS_DIR, exist_ok=True)
    os.makedirs(SYSTEM_DIR, exist_ok=True)
    os.makedirs(VERSIONS_DIR, exist_ok=True)

def _iso_stamp() -> str:
    # Filename-safe ISO (no ':')
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(":", "_")

def _file_path_for(name: str) -> str:
    # Whitelisted names only
    if name not in ALLOWED_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid name. Allowed: {sorted(ALLOWED_NAMES)}")
    return os.path.join(BUSINESS_DIR, f"{name}.md")

def _read_utf8(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read {path}: {e}")

def _write_utf8(path: str, content: str) -> None:
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write {path}: {e}")

def _backup_file(name: str, content: str, note: Optional[str]) -> str:
    _ensure_dirs()
    stamp = _iso_stamp()
    note_suffix = ""
    if note:
        # make a tiny, filename-safe suffix (trim to 24 chars)
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", note.strip())[:24].strip("-")
        if safe:
            note_suffix = f"-{safe}"
    filename = f"{name}-{stamp}{note_suffix}.md"
    path = os.path.join(VERSIONS_DIR, filename)
    _write_utf8(path, content)
    return filename

def _stat_info(path: str) -> Dict[str, Any]:
    try:
        st = os.stat(path)
        return {
            "exists": True,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
        }
    except FileNotFoundError:
        return {"exists": False, "size": 0, "mtime": None}

def _enforce_auth_or_local(request: Request) -> None:
    client_host = (request.client.host if request.client else None) or ""
    # If ADMIN_KEY is set → require it
    if ADMIN_KEY:
        key = request.headers.get("X-Admin-Key")
        if not key or key != ADMIN_KEY:
            raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Key.")
        return
    # Else: allow only localhost to reduce risk during dev
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Admin API allowed only from localhost in dev (no ADMIN_KEY set).")

# ---------- Models ----------
class UpdateFileBody(BaseModel):
    content: str = Field(..., description="UTF-8 markdown, ≤ 5KB")
    note: Optional[str] = Field(None, description="Optional change note (for backup filename)")

class RollbackBody(BaseModel):
    name: Literal["profile", "policies", "glossary"]
    backup: str = Field(..., description="A filename from /prompts/.versions to restore")

# ---------- Endpoints ----------
@router.get("/files")
async def list_files(request: Request):
    _enforce_auth_or_local(request)
    _ensure_dirs()
    items: List[Dict[str, Any]] = []
    for name in sorted(ALLOWED_NAMES):
        path = _file_path_for(name)
        st = _stat_info(path)
        items.append({"name": name, **st})
    return {
        "prompts_root": PROMPTS_ROOT,
        "business_dir": BUSINESS_DIR,
        "files": items,
    }

@router.get("/file/{name}")
async def read_file(name: str, request: Request):
    _enforce_auth_or_local(request)
    _ensure_dirs()
    path = _file_path_for(name)
    content = _read_utf8(path)
    return {"name": name, "content": content, "size": len(content.encode("utf-8"))}

@router.put("/file/{name}")
async def update_file(name: str, body: UpdateFileBody = Body(...), request: Request = None):
    _enforce_auth_or_local(request)
    _ensure_dirs()
    path = _file_path_for(name)

    # Validate UTF-8 + size
    try:
        raw = body.content.encode("utf-8")
    except UnicodeEncodeError:
        raise HTTPException(status_code=400, detail="Content must be valid UTF-8 text.")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"Content too large (>{MAX_BYTES} bytes).")

    # Read current for backup
    current = _read_utf8(path)
    backup_filename = _backup_file(name, current, note=f"before-{body.note or 'update'}") if current else None

    # Overwrite
    _write_utf8(path, body.content)

    # Soft reload prompt cache (same as /admin/prompts/reload)
    prompt_loader.reload()

    return {
        "ok": True,
        "name": name,
        "bytes": len(raw),
        "backup": backup_filename,
        "reloaded": True,
    }

@router.post("/reload")
async def reload_prompts(request: Request):
    _enforce_auth_or_local(request)
    prompt_loader.reload()
    return {"ok": True}

@router.post("/preview")
async def preview_prompts(request: Request):
    _enforce_auth_or_local(request)
    banner = await get_capabilities_banner_text()
    actor_header = get_actor_prompt_header()
    picker_header = get_picker_prompt_header()
    final_actor = (banner + "\n\n" + actor_header).strip() if actor_header else banner
    return {
        "banner_preview": banner[:800],
        "actor_header_preview": actor_header[:1200],
        "picker_header_preview": picker_header[:1200],
        "final_actor_preview": final_actor[:1600],
        "lengths": {
            "banner": len(banner or ""),
            "actor_header": len(actor_header or ""),
            "picker_header": len(picker_header or ""),
            "final_actor": len(final_actor or ""),
        },
    }

@router.post("/rollback")
async def rollback_file(body: RollbackBody = Body(...), request: Request = None):
    _enforce_auth_or_local(request)
    _ensure_dirs()
    # Validate backup filename shape to avoid path traversal
    if not re.fullmatch(rf"{body.name}-[A-Za-z0-9T_\-]+\.md", body.backup):
        raise HTTPException(status_code=400, detail="Invalid backup filename format.")
    backup_path = os.path.join(VERSIONS_DIR, body.backup)
    if not os.path.isfile(backup_path):
        raise HTTPException(status_code=404, detail="Backup not found.")

    content = _read_utf8(backup_path)
    path = _file_path_for(body.name)
    # Backup current before restore
    current = _read_utf8(path)
    backup_filename = _backup_file(body.name, current, note="before-rollback") if current else None

    _write_utf8(path, content)
    prompt_loader.reload()

    return {"ok": True, "restored": body.name, "from": body.backup, "backup_of_previous": backup_filename}
