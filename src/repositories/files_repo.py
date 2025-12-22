from __future__ import annotations
"""
files_repo.py — CRUD helpers for 'files' collection
"""

from typing import List, Optional, Dict, Any
from bson import ObjectId
from src.db.mongo import get_db

async def get_file(file_id: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    # accept both ObjectId and legacy string ids
    doc = None
    try:
        oid = ObjectId(file_id)
        doc = await db.files.find_one({"_id": oid})
    except Exception:
        doc = None
    if doc is None:
        doc = await db.files.find_one({"_id": file_id})
    if not doc:
        return None
    # normalize for API
    if isinstance(doc.get("_id"), ObjectId):
        doc["_id"] = str(doc["_id"])
    if isinstance(doc.get("session_id"), ObjectId):
        doc["session_id"] = str(doc["session_id"])
    return doc

async def get_files(file_ids: List[str]) -> List[Dict[str, Any]]:
    db = get_db()
    # try ObjectId set first; skip items that aren't valid OIDs
    oids = []
    for fid in file_ids:
        try:
            oids.append(ObjectId(fid))
        except Exception:
            continue
    if not oids:
        return []
    cur = db.files.find({"_id": {"$in": oids}})
    out: List[Dict[str, Any]] = []
    async for d in cur:
        if isinstance(d.get("_id"), ObjectId):
            d["_id"] = str(d["_id"])
        if isinstance(d.get("session_id"), ObjectId):
            d["session_id"] = str(d["session_id"])
        out.append(d)
    return out
