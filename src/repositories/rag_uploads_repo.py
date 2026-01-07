from __future__ import annotations

from typing import List, Dict, Any
from datetime import datetime, timezone

from src.db.mongo import get_db

COL_RAG_UPLOADS = "rag_uploads"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def log_upload(
    tenant_id: str,
    vector_store_id: str,
    uploaded: List[Dict[str, Any]],
) -> None:
    if not uploaded:
        return
    db = get_db()
    await db[COL_RAG_UPLOADS].insert_one(
        {
            "tenant_id": tenant_id,
            "vector_store_id": vector_store_id,
            "uploaded": uploaded,
            "file_count": len(uploaded),
            "created_at": _now_iso(),
        }
    )
