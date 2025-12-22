# src/feature_modules/file_content/utils.py
from __future__ import annotations
import mimetypes
import re
from hashlib import sha256 as _sha256
from pathlib import Path

_DISP_SAFE_RE = re.compile(r'[\r\n"]')  # strip controls and quotes

def sanitize_filename(name: str) -> str:
    if not name:
        return "file"
    name = _DISP_SAFE_RE.sub("", name).strip()
    return name or "file"

def _percent_encode(b: bytes) -> str:
    out = []
    for c in b:
        if (
            0x30 <= c <= 0x39 or  # 0-9
            0x41 <= c <= 0x5A or  # A-Z
            0x61 <= c <= 0x7A or  # a-z
            c in (0x2D, 0x2E, 0x5F, 0x7E)  # - . _ ~
        ):
            out.append(chr(c))
        else:
            out.append(f"%{c:02X}")
    return "".join(out)

def build_content_disposition(filename: str, attachment: bool) -> str:
    safe = sanitize_filename(filename)
    disp = "attachment" if attachment else "inline"
    filename_star = "UTF-8''" + _percent_encode(safe.encode("utf-8"))
    return f'{disp}; filename="{safe}"; filename*={filename_star}'

def guess_mime_from_path(p: Path, fallback: str = "application/octet-stream") -> str:
    mt, _ = mimetypes.guess_type(str(p))
    return mt or fallback

def compute_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = _sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
