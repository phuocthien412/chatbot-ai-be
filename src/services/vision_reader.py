# src/services/vision_reader.py
from __future__ import annotations
"""
vision_reader.py

Synchronous, low-latency "quick read" of an image to extract:
- caption (1-2 Vietnamese sentences)
- ocr (compact Vietnamese plain text)
- tags (<=5 coarse labels)

Designed to be called inline from the upload flow *before* chat_turn,
so the first assistant reply already "knows" what's in the image.

If the call fails or the file is too large, returns None.
"""

import base64
import json
import os
from typing import Optional, Dict, Any
import asyncio

from openai import OpenAI
from src.config import settings

# Hard guard to avoid huge payloads without adding new deps (Pillow).
# If image > this threshold, we skip analysis (keep upload fast).
VISION_MAX_BYTES = int(os.environ.get("VISION_MAX_BYTES", "5242880"))  # 5MB default

def _to_data_url(file_path: str, mime: str) -> Optional[str]:
    try:
        size = os.path.getsize(file_path)
        if size > VISION_MAX_BYTES:
            return None
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None

def _build_messages(data_url: str) -> list[dict]:
    sys_text = (
        "Bạn là công cụ trích xuất nội dung từ ảnh, trả về JSON ngắn gọn bằng tiếng Việt.\n"
        "YÊU CẦU:\n"
        "- Chỉ trả về JSON, không thêm lời dẫn.\n"
        "- Trường 'caption': 1-2 câu tóm tắt nội dung ảnh, ngắn gọn, tiếng Việt.\n"
        "- Trường 'ocr': văn bản trích xuất ngắn gọn (<= 500 ký tự). Có thể rút gọn, bỏ phần lặp.\n"
        "- Trường 'tags': mảng tối đa 5 từ/nhãn ngắn.\n"
    )
    user_parts = [
        {"type": "text", "text": "Đọc ảnh và TRẢ VỀ JSON với khóa: caption, ocr, tags."},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    return [
        {"role": "system", "content": sys_text},
        {"role": "user", "content": user_parts},
    ]

def _call_openai_sync(data_url: str, timeout_s: int) -> Optional[Dict[str, Any]]:
    client = OpenAI(api_key=settings.openai_api_key)
    model = (
        (getattr(settings, "openai_model_vision", None))
        or settings.openai_model_actor
        or settings.openai_model
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=_build_messages(data_url),
            timeout=timeout_s,
        )
        text = (resp.choices[0].message.content or "").strip()
        # try to locate JSON in the response
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end+1]
        data = json.loads(text)
        caption = str(data.get("caption", "")).strip()
        ocr = str(data.get("ocr", "")).strip()
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t)[:24] for t in tags][:5]
        return {"caption": caption, "ocr": ocr, "tags": tags}
    except Exception:
        return None

async def quick_read_image(file_path: str, mime: str, timeout_s: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Returns dict(caption, ocr, tags) or None on failure/skip.
    """
    if not (mime or "").lower().startswith("image/"):
        return None
    data_url = _to_data_url(file_path, mime or "image/jpeg")
    if not data_url:
        return None
    timeout = int(timeout_s or settings.request_timeout_seconds)
    # Call the sync OpenAI client in a thread to keep the event loop responsive
    return await asyncio.to_thread(_call_openai_sync, data_url, timeout)
