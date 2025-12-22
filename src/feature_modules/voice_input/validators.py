from fastapi import UploadFile, HTTPException
from typing import Set

async def read_and_check_size(upload: UploadFile, max_bytes: int) -> bytes:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file.")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Audio too large (> {max_bytes} bytes).")
    return data

def ensure_allowed_mime(upload: UploadFile, allowed_mime: Set[str], allowed_ext: Set[str]) -> None:
    ctype = (upload.content_type or "").split(";")[0].strip().lower()
    if ctype in allowed_mime:
        return
    name = (upload.filename or "").lower()
    if any(name.endswith(ext) for ext in allowed_ext):
        return
    raise HTTPException(status_code=415, detail=f"Unsupported media type: {ctype or 'unknown'}")
