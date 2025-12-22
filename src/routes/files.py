from __future__ import annotations
"""
File upload endpoint (synchronous vision quick-read + auto chat turn).

POST /files/upload  (multipart/form-data)
  form-data:
    - session_id: str  (required; must exist)
    - file: UploadFile (required; exactly one file per call)
    - field_hint: str  (optional; e.g., "file_x_closeup" to nudge the model)

Behavior:
  1) Save the file to disk (uploads/YYYY/MM/<uuid>.<ext>), record metadata in Mongo ('files' collection).
  2) Run a *fast* vision analysis for images (time-boxed) and embed the result into the auto user message.
  3) Immediately post a 'user' turn by invoking chat_turn(session_id, auto_text) so the assistant replies right after the upload.
  4) Return both file metadata and the assistant's reply/suggestions.
"""

import os
import uuid
import mimetypes
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
from fastapi.responses import JSONResponse

from bson import ObjectId

from src.db.mongo import get_db
from src.repositories import sessions_repo
from src.services.chat_service import chat_turn
from src.services.vision_reader import quick_read_image

router = APIRouter(prefix="/files", tags=["files"])

# --- Config (env-driven) ---
UPLOAD_ROOT = os.environ.get("UPLOAD_ROOT", os.path.join(os.getcwd(), "uploads"))
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "25"))

# comma-separated; wildcard 'image/*' allowed
_DEFAULT_ALLOWED = "image/jpeg,image/png,image/webp,application/pdf"
ALLOWED_MIME = {m.strip().lower() for m in os.environ.get("ALLOWED_MIME", _DEFAULT_ALLOWED).split(",") if m.strip()}

CHUNK_SIZE = 1024 * 1024  # 1MB chunks

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _is_allowed(mime: str) -> bool:
    mime = (mime or "").lower()
    if mime in ALLOWED_MIME:
        return True
    # wildcard support like image/*
    major = mime.split("/", 1)[0] if "/" in mime else ""
    if f"{major}/*" in ALLOWED_MIME:
        return True
    return False

def _ext_for_mime(mime: str, fallback: str = "") -> str:
    guess = mimetypes.guess_extension(mime or "")
    if guess:
        return guess.lstrip(".")
    return fallback.lstrip(".") if fallback else ""

@router.post("/upload")
async def upload_file(
    session_id: str = Form(...),
    file: UploadFile = File(...),
    field_hint: str | None = Form(None),
):
    # 0) Validate session
    session = await sessions_repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    # 1) MIME check
    mime = (file.content_type or "").lower()
    if not _is_allowed(mime):
        raise HTTPException(status_code=400, detail=f"Unsupported MIME type: {mime}")

    # 2) Build path
    now = datetime.now(timezone.utc)
    yyyy = now.strftime("%Y")
    mm = now.strftime("%m")
    save_dir = os.path.join(UPLOAD_ROOT, yyyy, mm)
    _ensure_dir(save_dir)

    # filename & ext
    original_name = getattr(file, "filename", None) or "upload.bin"
    ext = _ext_for_mime(mime) or (original_name.rsplit(".", 1)[1] if "." in original_name else "")
    uid = uuid.uuid4().hex
    save_name = f"{uid}.{ext}" if ext else uid
    save_path = os.path.join(save_dir, save_name)

    # 3) Stream to disk with size guard
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    total = 0
    try:
        with open(save_path, "wb") as out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    out.close()
                    try:
                        os.remove(save_path)
                    except OSError:
                        pass
                    raise HTTPException(status_code=400, detail=f"File too large (>{MAX_FILE_SIZE_MB}MB)")
                out.write(chunk)
    finally:
        await file.close()

    # 4) Record in DB
    db = get_db()
    doc = {
        "session_id": ObjectId(session_id),
        "original_name": original_name,
        "mime": mime,
        "size": total,
        "storage": {"kind": "disk", "path": save_path},
        "created_at": now.isoformat(),
    }
    res = await db.files.insert_one(doc)
    file_id = str(res.inserted_id)

    file_payload = {
        "file_id": file_id,
        "session_id": session_id,
        "original_name": original_name,
        "mime": mime,
        "size": total,
        "created_at": now.isoformat(),
    }

    # 5) Compose an auto user message for the chat flow
    #    Keep it clear so LLM can map to the spec fields (file fields are arrays of IDs).
    lines = [
        f"Đã tải tệp: {original_name}",
        f"ID tệp: {file_id}",
        f"Loại: {mime}, kích thước: {total} bytes.",
    ]
    if field_hint:
        lines.append(f"Gợi ý trường: {field_hint}")
        lines.append("Hãy dùng ID này cho trường trên nếu phù hợp.")

    # 5.1) Synchronous quick vision pass for images
    if mime.startswith("image/"):
        try:
            info = await quick_read_image(save_path, mime)
            if info:
                caption = (info.get("caption") or "").strip()
                ocr = (info.get("ocr") or "").strip()
                tags = info.get("tags") or []
                if caption or ocr or tags:
                    lines.append("")  # blank line
                    lines.append("— AI đọc ảnh (nhanh) —")
                    if caption:
                        lines.append(f"Tóm tắt: {caption}")
                    if ocr:
                        # cap length to keep the message compact
                        if len(ocr) > 700:
                            ocr = ocr[:700].rstrip() + "…"
                        lines.append("OCR (rút gọn):")
                        lines.append(ocr)
                    if tags:
                        tags_line = ", ".join(str(t) for t in tags[:5])
                        lines.append(f"Nhãn: {tags_line}")
        except Exception:
            # Fail silently; we don't want to block uploads
            pass

    auto_text = "\n".join(lines)

    chat_result = None
    chat_error = None

    # 6) Immediately run the normal chat flow so the assistant replies
    try:
        # chat_turn writes the user message and returns assistant reply + suggestions
        assistant_message_id, reply, suggestions = await chat_turn(session_id, auto_text)
        chat_result = {
            "assistant_message_id": assistant_message_id,
            "reply": reply,
            "suggestions": suggestions or [],
            "auto_user_message": auto_text,
        }
    except Exception as e:
        # We still return the file info; chat failure is non-fatal to upload
        chat_error = {"message": "Auto-reply failed", "detail": str(e)}

    # 7) Response
    payload = {"file": file_payload}
    if chat_result:
        payload["chat"] = chat_result
    if chat_error:
        payload["chat_error"] = chat_error

    return JSONResponse(payload, status_code=status.HTTP_201_CREATED)
