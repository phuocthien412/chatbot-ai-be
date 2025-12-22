# src/feature_modules/file_content/backends/mongo_store.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, Any, Dict

from bson import ObjectId

from ..models import FileMeta
from ..utils import guess_mime_from_path
from ..config import FILES_STORAGE_ROOT  # used only if a stored path is relative
from ..appdb import get_app_database


async def lookup(file_id: str) -> Optional[FileMeta]:
    """
    Resolve FileMeta by Mongo _id (string) from YOUR app's existing Mongo connection.
    Expected document shape (matches your upload API):
      {
        _id: ObjectId(...),
        original_name: str,
        mime: str,
        size: int,
        storage: { kind: "disk", path: "<ABSOLUTE or RELATIVE PATH>" },
        sha256: str (optional)
      }
    """
    try:
        oid = ObjectId(file_id)
    except Exception:
        return None

    db = await get_app_database()
    coll = db.get_collection("files")  # your upload pipeline stores here
    doc: Optional[Dict[str, Any]] = await coll.find_one({"_id": oid})
    if not doc:
        return None

    storage = doc.get("storage") or {}
    kind = (storage.get("kind") or "disk").lower()
    if kind != "disk":
        # Only disk-backed blobs supported in this feature
        return None

    raw_path = storage.get("path")
    if not raw_path:
        return None

    p = Path(raw_path)
    if not p.is_absolute():
        p = (FILES_STORAGE_ROOT / p).resolve()

    original_name = doc.get("original_name") or p.name
    mime = doc.get("mime") or guess_mime_from_path(p)
    size = doc.get("size")
    sha256 = doc.get("sha256")

    return FileMeta(
        file_id=file_id,
        abs_path=p,
        original_name=original_name,
        mime=mime,
        size=size,
        sha256=sha256,
    )
