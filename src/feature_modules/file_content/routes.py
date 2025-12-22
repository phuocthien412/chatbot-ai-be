# src/feature_modules/file_content/routes.py
from __future__ import annotations
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from starlette.responses import StreamingResponse, JSONResponse

from .config import PUBLIC_BY_ID
from .store import file_index
from .services import (
    _iter_file,
    _parse_range,
    build_headers,
    resolve_if_none_match,
)
from .utils import guess_mime_from_path

router = APIRouter(prefix="/files", tags=["files"])

@router.options("/{file_id}/content")
async def files_content_options(file_id: str) -> Response:
    resp = Response(status_code=204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Range, If-None-Match, Accept"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp

@router.get("/{file_id}/content")
async def files_content(
    request: Request,
    file_id: str,
    download: int = Query(0, ge=0, le=1, description="0=inline (default), 1=attachment"),
):
    if not PUBLIC_BY_ID:
        raise HTTPException(status_code=403, detail="Forbidden")

    meta = await file_index.lookup(file_id)
    if not meta:
        return JSONResponse(status_code=404, content={"ok": False, "detail": "not found"})

    p: Path = meta.abs_path
    if not p.exists():
        return JSONResponse(status_code=410, content={"ok": False, "detail": "gone"})

    req_etag = resolve_if_none_match(request)
    resp_headers = build_headers(meta, download=bool(download), etag_seed=meta.file_id)
    if req_etag and req_etag == resp_headers.get("ETag", "").strip('"'):
        resp = Response(status_code=304)
        for k, v in resp_headers.items():
            if k.lower() != "content-length":
                resp.headers[k] = v
        return resp

    total = p.stat().st_size
    mime = meta.mime or guess_mime_from_path(p)

    range_header = request.headers.get("range")
    rng = _parse_range(range_header, total) if range_header else None

    if rng:
        start, end_excl = rng
        if start >= end_excl or start < 0 or end_excl > total:
            return JSONResponse(
                status_code=416,
                content={"ok": False, "detail": "invalid range"},
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Range": f"bytes */{total}",
                },
            )
        length = end_excl - start
        headers = {
            **resp_headers,
            "Content-Type": mime,
            "Content-Length": str(length),
            "Content-Range": f"bytes {start}-{end_excl - 1}/{total}",
        }
        return StreamingResponse(
            _iter_file(p, start=start, end_excl=end_excl),
            media_type=mime,
            status_code=206,
            headers=headers,
        )

    headers = {
        **resp_headers,
        "Content-Type": mime,
        "Content-Length": str(total),
    }
    return StreamingResponse(
        _iter_file(p, start=0, end_excl=None),
        media_type=mime,
        status_code=200,
        headers=headers,
    )

def register(app) -> None:
    """
    Attach this feature's router:
        from feature_modules.file_content import register as register_file_content
        register_file_content(app)
    """
    app.include_router(router)
