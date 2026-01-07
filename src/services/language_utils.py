from __future__ import annotations

import re
from typing import Optional

_VI_DIACRITICS_RE = re.compile(
    r"["
    r"àáạảãâầấậẩẫăằắặẳẵ"
    r"èéẹẻẽêềếệểễ"
    r"ìíịỉĩ"
    r"òóọỏõôồốộổỗơờớợởỡ"
    r"ùúụủũưừứựửữ"
    r"ỳýỵỷỹ"
    r"đ"
    r"]",
    re.IGNORECASE,
)

_VI_WORDS_RE = re.compile(
    r"\b("
    r"toi|ban|minh|khong|gi|sao|bao|nhieu|"
    r"cam on|xin chao|chao|hoi"
    r")\b",
    re.IGNORECASE,
)


def normalize_language(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    if raw in {"auto", "detect"}:
        return "auto"
    if raw.startswith("vi"):
        return "vi"
    if raw.startswith("en"):
        return "en"
    return None


def detect_language(text: str) -> str:
    if not text:
        return "en"
    if _VI_DIACRITICS_RE.search(text):
        return "vi"
    if _VI_WORDS_RE.search(text):
        return "vi"
    return "en"


def language_directive(language: Optional[str]) -> str:
    lang = normalize_language(language)
    if lang == "vi":
        return "Respond in Vietnamese."
    if lang == "en":
        return "Respond in English."
    return ""
