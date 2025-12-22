# src/feature_modules/file_content/services.py
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

from fastapi import Request

from .models import FileMeta
from .utils import build_content_disposition, compute_sha256

_CHUNK = 1024 * 64  # 64 KiB

def _utc_http_date(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

def _iter_file(path: Path, start: int = 0, end_excl: Optional[int] = None) -> Iterator[bytes]:
    with path.open("rb") as f:
        if start:
            f.seek(start)
        remaining = None if end_excl is None else (end_excl - start)
        while True:
            read_size = _CHUNK if remaining is None else min(_CHUNK, remaining)
            if read_size <= 0:
                break
            data = f.read(read_size)
            if not data:
                break
            if remaining is not None:
                remaining -= len(data)
            yield data

def _parse_range(range_header: str, total: int) -> Optional[Tuple[int, int]]:
    if not range_header or not range_header.startswith("bytes="):
        return None
    try:
        val = range_header.split("=", 1)[1].strip()
        if "," in val:
            return None
        start_s, end_s = val.split("-", 1)
        if start_s == "" and end_s == "":
            return None
        if start_s == "":
            length = int(end_s)
            if length <= 0:
                return None
            start = max(total - length, 0)
            return (start, total)
        start = int(start_s)
        if end_s == "":
            end_excl = total
        else:
            end = int(end_s)
            if end < start:
                return None
            end_excl = end + 1
        if start >= total:
            return None
        return (start, min(end_excl, total))
    except Exception:
        return None

def build_headers(meta: FileMeta, *, download: bool, etag_seed: Optional[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    headers["Access-Control-Allow-Origin"] = "*"
    headers["Cache-Control"] = "public, max-age=31536000, immutable"

    etag = meta.sha256 or etag_seed or meta.file_id
    # Final fallback: compute (one-time cost); comment out if you don't want IO here.
    if not etag:
        try:
            etag = compute_sha256(meta.abs_path)
        except Exception:
            etag = meta.file_id

    headers["ETag"] = f"\"{etag}\""
    headers["Content-Disposition"] = build_content_disposition(meta.original_name, download)
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Accept-Ranges"] = "bytes"
    headers["Date"] = _utc_http_date(datetime.now(timezone.utc))
    return headers

def resolve_if_none_match(request: Request) -> Optional[str]:
    inm = request.headers.get("if-none-match")
    if not inm:
        return None
    token = inm.split(",")[0].strip()
    return token.strip('"')
