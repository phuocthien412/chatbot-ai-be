from __future__ import annotations

from typing import List
from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException, Depends
from openai import OpenAI

from src.config import settings
from src.security.deps import admin_guard, RequestContext
from src.security.permissions import ensure_permission
from .models import VectorStoreOut, DocOut, DocListOut, DocListItem, OpOut
from .service_openai import (
    get_or_create_vector_store,
    link_existing_vector_store,
    upload_files_to_vector_store,
    list_vector_store_files,
    hard_delete_file_from_store,
)
from src.repositories import info_search_docs_repo
from src.repositories import rag_uploads_repo
from src.db.mongo import get_db

router = APIRouter(prefix="/admin/info-search", tags=["admin.info-search"])


@router.post("/vector-store", response_model=VectorStoreOut)
async def admin_create_or_get_vector_store(
    tenant_id: str = Form(default="default"),
    ctx: RequestContext = Depends(admin_guard),
):
    await ensure_permission(ctx, "knowledge_base", "refresh")
    client = OpenAI(api_key=settings.openai_api_key)
    print(settings.openai_api_key)
    vs_id = await get_or_create_vector_store(client, tenant_id)
    return VectorStoreOut(tenant_id=tenant_id, vector_store_id=vs_id)

@router.get("/vector-store/get", response_model=VectorStoreList)
async def get_vector_store():
    db = get_db()["info_search_tenants"]
    docs = await db.find(
        {},
        {"_id": 0, "tenant_id": 1}
    ).to_list(length=None)
    print(docs)
    return VectorStoreList(tenant_id_list=[doc["tenant_id"] for doc in docs] or None)

@router.post("/vector-store/link", response_model=VectorStoreOut)
async def admin_link_vector_store(
    tenant_id: str = Form(default="default"),
    vector_store_id: str = Form(...),
    ctx: RequestContext = Depends(admin_guard),
):
    await ensure_permission(ctx, "knowledge_base", "refresh")
    client = OpenAI(api_key=settings.openai_api_key)
    try:
        vs_id = await link_existing_vector_store(client, tenant_id, vector_store_id)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    return VectorStoreOut(tenant_id=tenant_id, vector_store_id=vs_id)


@router.post("/docs", response_model=List[DocOut])
async def admin_upload_docs(
    files: List[UploadFile] = File(..., description="One or more documents"),
    tenant_id: str = Form(default="default"),
    ctx: RequestContext = Depends(admin_guard),
):
    await ensure_permission(ctx, "knowledge_base", "upload")
    if not files:
        raise HTTPException(400, "No files provided")
    client = OpenAI(api_key=settings.openai_api_key)
    vs_id = await get_or_create_vector_store(client, tenant_id)

    try:
        uploaded = await upload_files_to_vector_store(client, vs_id, files)
        await info_search_docs_repo.upsert_docs(
            tenant_id,
            vs_id,
            [
                {
                    "file_id": f_id,
                    "filename": fn,
                    "bytes": sz,
                    "status": "ready",
                }
                for (f_id, fn, sz) in uploaded
            ],
        )
        await rag_uploads_repo.log_upload(
            tenant_id=tenant_id,
            vector_store_id=vs_id,
            uploaded=[{"file_id": f_id, "filename": fn, "bytes": sz} for (f_id, fn, sz) in uploaded],
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    return [
        DocOut(file_id=f_id, filename=fn, bytes=sz, status="ready", vector_store_id=vs_id)
        for (f_id, fn, sz) in uploaded
    ]


@router.get("/docs", response_model=DocListOut)
async def admin_list_docs(
    tenant_id: str = Query(default="default"),
    ctx: RequestContext = Depends(admin_guard),
):
    await ensure_permission(ctx, "knowledge_base", "view")
    client = OpenAI(api_key=settings.openai_api_key)
    vs_id = await get_or_create_vector_store(client, tenant_id)

    try:
        existing = {d.get("file_id"): d for d in (await info_search_docs_repo.list_docs(tenant_id, vs_id))}  # type: ignore
        resp = list_vector_store_files(client, vs_id)
        raw_items = [
            {
                "file_id": f.id,
                "filename": getattr(f, "filename", None) or (existing.get(f.id, {}) or {}).get("filename"),
                "bytes": getattr(f, "bytes", None) or (existing.get(f.id, {}) or {}).get("bytes"),
                "created_at": getattr(f, "created_at", None) or (existing.get(f.id, {}) or {}).get("created_at"),
                "status": getattr(f, "status", None) or (existing.get(f.id, {}) or {}).get("status"),
            }
            for f in resp.data
        ]
        if raw_items:
            try:
                await info_search_docs_repo.upsert_docs(tenant_id, vs_id, raw_items)
            except Exception:
                pass
    except Exception:
        pass

    docs = await info_search_docs_repo.list_docs(tenant_id, vs_id)
    items: List[DocListItem] = [
        DocListItem(
            file_id=d.get("file_id"),
            filename=d.get("filename"),
            bytes=d.get("bytes"),
            status=d.get("status"),
            created_at=d.get("created_at"),
        )
        for d in docs
    ]
    return DocListOut(vector_store_id=vs_id, items=items)


@router.delete("/docs/{file_id}", response_model=OpOut)
async def admin_delete_doc(
    file_id: str,
    tenant_id: str = Query(default="default"),
    ctx: RequestContext = Depends(admin_guard),
):
    await ensure_permission(ctx, "knowledge_base", "delete")
    client = OpenAI(api_key=settings.openai_api_key)
    vs_id = await get_or_create_vector_store(client, tenant_id)
    hard_delete_file_from_store(client, vs_id, file_id)
    try:
        await info_search_docs_repo.delete_doc(tenant_id, file_id)
    except Exception:
        pass
    return OpOut(ok=True, detail="deleted")
