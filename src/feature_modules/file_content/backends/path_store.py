# src/feature_modules/file_content/backends/path_store.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional, Dict, Any

from ..config import FILES_STORAGE_ROOT, FILES_INDEX_PATH, FILES_FALLBACK_TO_PATH
from ..models import FileMeta
from ..utils import guess_mime_from_path

_index_cache: Dict[str, Dict[str, Any]] = {}
if FILES_INDEX_PATH:
    p = Path(FILES_INDEX_PATH)
    if p.exists():
        _index_cache = json.loads(p.read_text(encoding="utf-8"))

async def lookup(file_id: str) -> Optional[FileMeta]:
    # Try explicit JSON index
    entry = _index_cache.get(file_id)
    if entry:
        abs_path = Path(entry["path"])
        if not abs_path.is_absolute():
            abs_path = (FILES_STORAGE_ROOT / abs_path).resolve()
        original_name = entry.get("original_name") or abs_path.name
        mime = entry.get("mime") or guess_mime_from_path(abs_path)
        size = entry.get("size")
        sha256 = entry.get("sha256")
        return FileMeta(file_id, abs_path, original_name, mime, size, sha256)

    # Fallback: treat file_id as relative path under root
    if FILES_FALLBACK_TO_PATH:
        rel = Path(file_id)
        if not rel.is_absolute() and ".." not in rel.parts:
            abs_path = (FILES_STORAGE_ROOT / rel).resolve()
            if abs_path.exists():
                return FileMeta(
                    file_id=file_id,
                    abs_path=abs_path,
                    original_name=abs_path.name,
                    mime=guess_mime_from_path(abs_path),
                    size=abs_path.stat().st_size,
                    sha256=None,
                )
    return None
