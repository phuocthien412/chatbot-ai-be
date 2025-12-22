from __future__ import annotations
import os, hashlib, uuid, datetime
from typing import Optional, Dict, Any
from bson import ObjectId
from fastapi import HTTPException

from src.db.mongo import get_db
from .providers.openai_tts import synthesize_bytes as openai_synthesize
from .config import TTSConfig as Cfg

# Reuse same uploads root pattern as file upload route
UPLOAD_ROOT = os.environ.get("UPLOAD_ROOT", os.path.join(os.getcwd(), "uploads"))

def _hash_key(text: str, provider: str, voice: str, fmt: str, speed: float|None, pitch: int|None) -> str:
    norm = f"{text}\n|p={provider}|v={voice}|f={fmt}|s={speed}|t={pitch}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()

async def _lookup_cache(hash_key: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    doc = await db.files.find_one({"category": "tts", "hash_key": hash_key})
    if doc:
        doc["_id"] = str(doc["_id"])
        if isinstance(doc.get("session_id"), ObjectId):
            doc["session_id"] = str(doc["session_id"])
    return doc

def _ext_for(fmt: str) -> str:
    return {"mp3": ".mp3", "opus": ".opus", "wav": ".wav"}.get(fmt, ".mp3")

def _mime_for(fmt: str) -> str:
    return {"mp3": "audio/mpeg", "opus": "audio/ogg", "wav": "audio/wav"}.get(fmt, "audio/mpeg")

async def _save_bytes_to_disk_and_db(content: bytes, fmt: str, session_id: Optional[str], hash_key: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    # 1) path
    today = datetime.datetime.now(datetime.timezone.utc)
    rel_dir = os.path.join("audio", today.strftime("%Y"), today.strftime("%m"))
    out_dir = os.path.join(UPLOAD_ROOT, rel_dir)
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{uuid.uuid4().hex}{_ext_for(fmt)}"
    disk_path = os.path.join(out_dir, fname)

    with open(disk_path, "wb") as f:
        f.write(content)

    # 2) DB
    db = get_db()
    doc = {
        "session_id": ObjectId(session_id) if session_id else None,
        "original_name": f"tts_{today.strftime('%Y%m%d_%H%M%S')}{_ext_for(fmt)}",
        "mime": _mime_for(fmt),
        "size": len(content),
        "storage": {"kind": "disk", "path": disk_path},
        "category": "tts",
        "hash_key": hash_key,
        "meta": meta,
        "created_at": today,
    }
    # Remove None fields for cleanliness
    if doc["session_id"] is None:
        del doc["session_id"]
    res = await db.files.insert_one(doc)
    file_id = str(res.inserted_id)
    return {
        "file_id": file_id,
        "url": f"/files/{file_id}/content",
        "meta": meta,
    }

async def synthesize_and_optionally_save(
    text: str,
    voice: Optional[str],
    fmt: str,
    speed: Optional[float],
    pitch: Optional[int],
    provider: str,
    session_id: Optional[str],
    save: bool,
) -> Dict[str, Any]:
    provider = provider or "openai"
    voice = voice or Cfg.default_voice()
    fmt = fmt or Cfg.default_format()
    speed = speed if speed is not None else 1.0
    pitch = pitch if pitch is not None else 0

    # Caching (only if saving)
    hash_key = _hash_key(text, provider, voice, fmt, speed, pitch) if save else None
    if save and hash_key:
        hit = await _lookup_cache(hash_key)
        if hit:
            return {"file_id": hit["_id"], "url": f"/files/{hit['_id']}/content", "meta": hit.get("meta", {})}

    # Synthesize
    if provider == "openai":
        content, meta = await openai_synthesize(text=text, voice=voice, fmt=fmt, speed=speed, pitch=pitch)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    if not save:
        # Return as "inline" bytes (caller route will marshal)
        return {"file_id": None, "url": None, "meta": meta, "bytes": content}

    # Save + return file url
    return await _save_bytes_to_disk_and_db(content, fmt, session_id, hash_key, meta)
