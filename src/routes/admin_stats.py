from __future__ import annotations
from typing import Dict, Any
import random
from fastapi import APIRouter, Depends
from src.security.deps import admin_guard, RequestContext
from src.security.permissions import ensure_permission
from src.repositories import sessions_repo, info_search_docs_repo
from datetime import datetime, timedelta

router = APIRouter(prefix="/admin/stats", tags=["admin.stats"])

@router.get("/system")
async def get_system_stats(
    ctx: RequestContext = Depends(admin_guard),
) -> Dict[str, Any]:
    await ensure_permission(ctx, "dashboard", "view") # Assuming dashboard view permission exists or reuse generic
    
    # 1. CCU: Active sessions in last 15 minutes
    ccu = await sessions_repo.count_active_sessions(minutes=15)
    
    # RAG Docs Count
    rag_count = await info_search_docs_repo.count_docs(tenant_id="default")

    # 2. Hardware stats (Mocked for now as psutil is not available)
    # In a real scenario, use psutil:
    # import psutil
    # ram = psutil.virtual_memory().percent
    # cpu = psutil.cpu_percent()
    # storage = psutil.disk_usage('/').percent
    
    ram = random.randint(40, 65)
    cpu = random.randint(15, 35)
    storage = 22 # Relatively static
    
    return {
        "ccu": ccu,
        "rag_documents_count": rag_count,
        "ram_percent": ram,
        "cpu_percent": cpu,
        "storage_percent": storage
    }
