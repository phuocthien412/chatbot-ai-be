from __future__ import annotations
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from pymongo import UpdateOne
from src.db.mongo import get_db

COL_INFO_DOCS = "info_search_docs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def upsert_docs(
    tenant_id: str,
    vector_store_id: str,
    docs: List[Dict[str, Any]],
) -> None:
    """
    Upsert documents metadata into Mongo.
    docs: list of dicts with keys: file_id, filename, bytes, status.
    """
    if not docs:
        return
    db = get_db()
    bulk: List[UpdateOne] = []
    for doc in docs:
        file_id = doc.get("file_id")
        if not file_id:
            continue
        bulk.append(
            UpdateOne(
                {"tenant_id": tenant_id, "file_id": file_id},
                {
                    "$set": {
                        "tenant_id": tenant_id,
                        "vector_store_id": vector_store_id,
                        "file_id": file_id,
                        "filename": doc.get("filename"),
                        "bytes": doc.get("bytes"),
                        "status": doc.get("status", "ready"),
                        "updated_at": _now_iso(),
                    },
                    "$setOnInsert": {
                        "created_at": _now_iso(),
                    },
                },
                upsert=True,
            )
        )
    if bulk:
        await db[COL_INFO_DOCS].bulk_write(bulk)


async def list_docs(tenant_id: str, vector_store_id: Optional[str] = None) -> List[Dict[str, Any]]:
    db = get_db()
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if vector_store_id:
        query["vector_store_id"] = vector_store_id
    cur = db[COL_INFO_DOCS].find(query).sort("created_at", -1)
    out: List[Dict[str, Any]] = []
    async for doc in cur:
        doc["_id"] = str(doc.get("_id"))
        out.append(doc)
    return out


async def delete_doc(tenant_id: str, file_id: str) -> None:
    db = get_db()
    await db[COL_INFO_DOCS].delete_one({"tenant_id": tenant_id, "file_id": file_id})
