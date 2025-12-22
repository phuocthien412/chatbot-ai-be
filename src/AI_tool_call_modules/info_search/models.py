# src/AI_tool_call_modules/info_search/models.py
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field

class VectorStoreOut(BaseModel):
    ok: bool = True
    tenant_id: str
    vector_store_id: str

class DocOut(BaseModel):
    ok: bool = True
    file_id: str
    filename: str
    bytes: Optional[int] = None
    status: str = "ready"
    vector_store_id: str

class DocListItem(BaseModel):
    file_id: str
    filename: Optional[str] = None
    bytes: Optional[int] = None
    created_at: Optional[int] = None

class DocListOut(BaseModel):
    ok: bool = True
    vector_store_id: str
    items: List[DocListItem] = Field(default_factory=list)

class OpOut(BaseModel):
    ok: bool = True
    detail: Optional[str] = None
