# src/AI_tool_call_modules/info_search/routes.py
from __future__ import annotations

from typing import List
from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException
from openai import OpenAI

from src.config import settings
from .models import VectorStoreOut, DocOut, DocListOut, DocListItem, OpOut
from .service_openai import (
    get_or_create_vector_store,
    link_existing_vector_store,
    upload_files_to_vector_store,
    list_vector_store_files,
    hard_delete_file_from_store,
)

router = APIRouter(prefix="/feature/info-search", tags=["info-search"])

@router.post("/vector-store", response_model=VectorStoreOut)
async def create_or_get_vector_store(tenant_id: str = Form(default="default")):
    client = OpenAI(api_key=settings.openai_api_key)
    vs_id = await get_or_create_vector_store(client, tenant_id)
    return VectorStoreOut(tenant_id=tenant_id, vector_store_id=vs_id)

@router.post("/vector-store/link", response_model=VectorStoreOut)
async def link_vector_store(
    tenant_id: str = Form(default="default"),
    vector_store_id: str = Form(...),
):
    client = OpenAI(api_key=settings.openai_api_key)
    try:
        vs_id = await link_existing_vector_store(client, tenant_id, vector_store_id)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    return VectorStoreOut(tenant_id=tenant_id, vector_store_id=vs_id)

@router.post("/docs", response_model=List[DocOut])
async def upload_docs(
    files: List[UploadFile] = File(..., description="One or more documents"),
    tenant_id: str = Form(default="default"),
):
    if not files:
        raise HTTPException(400, "No files provided")
    client = OpenAI(api_key=settings.openai_api_key)
    vs_id = await get_or_create_vector_store(client, tenant_id)

    try:
        uploaded = await upload_files_to_vector_store(client, vs_id, files)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    return [
        DocOut(file_id=f_id, filename=fn, bytes=sz, status="ready", vector_store_id=vs_id)
        for (f_id, fn, sz) in uploaded
    ]

@router.get("/docs", response_model=DocListOut)
async def list_docs(tenant_id: str = Query(default="default")):
    client = OpenAI(api_key=settings.openai_api_key)
    vs_id = await get_or_create_vector_store(client, tenant_id)
    resp = list_vector_store_files(client, vs_id)
    items = [
        DocListItem(
            file_id=f.id,
            filename=getattr(f, "filename", None),
            bytes=getattr(f, "bytes", None),
            created_at=getattr(f, "created_at", None),
        )
        for f in resp.data
    ]
    return DocListOut(vector_store_id=vs_id, items=items)

@router.delete("/docs/{file_id}", response_model=OpOut)
async def delete_doc(file_id: str, tenant_id: str = Query(default="default")):
    client = OpenAI(api_key=settings.openai_api_key)
    vs_id = await get_or_create_vector_store(client, tenant_id)
    hard_delete_file_from_store(client, vs_id, file_id)
    return OpOut(ok=True, detail="deleted")
