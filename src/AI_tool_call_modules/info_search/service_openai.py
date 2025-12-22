# src/AI_tool_call_modules/info_search/service_openai.py
from __future__ import annotations
from typing import Iterable, List, Tuple, Any, Callable, Optional
from fastapi import UploadFile
from openai import OpenAI
import asyncio

from src.db.mongo import get_db

COL_TENANTS = "info_search_tenants"

# ----------------------------
# SDK compatibility helpers
# ----------------------------
def _vec_api(client: OpenAI):
    vs = getattr(client, "vector_stores", None)
    if vs is not None:
        return vs
    beta = getattr(client, "beta", None)
    if beta is not None and hasattr(beta, "vector_stores"):
        return beta.vector_stores
    raise RuntimeError("Your openai SDK does not expose 'vector_stores'. Please upgrade 'openai' (e.g. >=1.55,<2).")

def _assistants_api(client: OpenAI):
    a = getattr(client, "assistants", None)
    if a is not None:
        return a
    beta = getattr(client, "beta", None)
    if beta is not None and hasattr(beta, "assistants"):
        return beta.assistants
    raise RuntimeError("Your openai SDK does not expose 'assistants' API.")

def _threads_api(client: OpenAI):
    t = getattr(client, "threads", None)
    if t is not None:
        return t
    beta = getattr(client, "beta", None)
    if beta is not None and hasattr(beta, "threads"):
        return beta.threads
    raise RuntimeError("Your openai SDK does not expose 'threads' API.")

# ----------------------------
# Vector store ops
# ----------------------------
async def get_or_create_vector_store(client: OpenAI, tenant_id: str) -> str:
    db = get_db()
    row = await db[COL_TENANTS].find_one({"tenant_id": tenant_id})
    if row and row.get("vector_store_id"):
        return row["vector_store_id"]

    vs_api = _vec_api(client)
    vs = vs_api.create(name=f"kb::{tenant_id}")
    await db[COL_TENANTS].update_one(
        {"tenant_id": tenant_id},
        {"$set": {"tenant_id": tenant_id, "vector_store_id": vs.id}},
        upsert=True,
    )
    return vs.id

async def link_existing_vector_store(client: OpenAI, tenant_id: str, vector_store_id: str) -> str:
    vs_api = _vec_api(client)
    # Try to validate if SDK supports it; otherwise assume ok
    if hasattr(vs_api, "retrieve") or hasattr(vs_api, "get"):
        try:
            if hasattr(vs_api, "retrieve"):
                _ = vs_api.retrieve(vector_store_id)
            else:
                _ = vs_api.get(vector_store_id)
        except Exception as e:
            raise ValueError(f"Vector store not found or not accessible: {vector_store_id}: {e}")

    db = get_db()
    await db[COL_TENANTS].update_one(
        {"tenant_id": tenant_id},
        {"$set": {"tenant_id": tenant_id, "vector_store_id": vector_store_id}},
        upsert=True,
    )
    return vector_store_id

async def upload_files_to_vector_store(
    client: OpenAI, vs_id: str, files: Iterable[UploadFile]
) -> List[Tuple[str, str, int | None]]:
    vs_api = _vec_api(client)
    out: List[Tuple[str, str, int | None]] = []

    create_and_poll: Callable[..., Any] | None = getattr(getattr(vs_api, "files", None), "create_and_poll", None)
    create_only: Callable[..., Any] | None = getattr(getattr(vs_api, "files", None), "create", None)

    for up in files:
        content = await up.read()
        try:
            await up.seek(0)
        except Exception:
            pass
        if not content:
            raise ValueError(f"Empty file upload: {up.filename or '(unnamed)'}")

        filename = up.filename or "upload.bin"
        size = len(content)

        f_obj = client.files.create(file=(filename, content), purpose="assistants")

        if create_and_poll:
            create_and_poll(vector_store_id=vs_id, file_id=f_obj.id)
        elif create_only:
            create_only(vector_store_id=vs_id, file_id=f_obj.id)
        else:
            raise RuntimeError("Your SDK lacks vector_stores.files.create[_and_poll]. Please upgrade openai.")

        out.append((f_obj.id, filename, size))

    return out

def list_vector_store_files(client: OpenAI, vs_id: str):
    vs_api = _vec_api(client)
    return vs_api.files.list(vector_store_id=vs_id)

def hard_delete_file_from_store(client: OpenAI, vs_id: str, file_id: str):
    vs_api = _vec_api(client)
    vs_api.files.delete(vector_store_id=vs_id, file_id=file_id)
    try:
        client.files.delete(file_id)
    except Exception:
        pass

# ----------------------------
# Assistants-based RAG fallback
# ----------------------------
async def get_or_create_assistant_for_tenant(client: OpenAI, tenant_id: str, vs_id: str, model_name: str) -> str:
    """
    Create (or reuse) an assistant bound to the tenant's vector store via file_search tool.
    Store assistant_id on the same tenant record in Mongo.
    """
    db = get_db()
    row = await db[COL_TENANTS].find_one({"tenant_id": tenant_id}) or {}
    if row.get("assistant_id"):
        return row["assistant_id"]

    assistants = _assistants_api(client)

    # Try to attach vector store at creation; if 'tool_resources' not supported, create without it,
    # then try to update; if still not supported, we still have the assistant with the tool,
    # and the run-time may still pick up the store by ID we pass on the run (below).
    kwargs = dict(
        name=f"info.search::{tenant_id}",
        instructions=(
            "You answer using the file_search tool against the provided knowledge base. "
            "Write concise, confident prose and weave source titles naturally into sentences. "
            "End with a brief 'Sources:' list."
        ),
        model=model_name,
        tools=[{"type": "file_search"}],
    )
    try:
        a = assistants.create(**kwargs, tool_resources={"file_search": {"vector_store_ids": [vs_id]}})
        assistant_id = a.id
    except Exception:
        a = assistants.create(**kwargs)
        assistant_id = a.id
        # Best-effort update with tool_resources if the SDK supports it
        try:
            assistants.update(assistant_id, tool_resources={"file_search": {"vector_store_ids": [vs_id]}})
        except Exception:
            pass

    await db[COL_TENANTS].update_one(
        {"tenant_id": tenant_id},
        {"$set": {"assistant_id": assistant_id}},
        upsert=True,
    )
    return assistant_id

async def assistants_rag_answer(
    client: OpenAI, tenant_id: str, vs_id: str, model_name: str, prompt_text: str, timeout_s: Optional[int] = 60
) -> str:
    assistants = _assistants_api(client)
    threads = _threads_api(client)

    assistant_id = await get_or_create_assistant_for_tenant(client, tenant_id, vs_id, model_name)

    # Create a thread and post the user message
    th = threads.create()
    _ = threads.messages.create(thread_id=th.id, role="user", content=prompt_text)

    # Try run with vector store resource at run-time; if not accepted, run without it
    try:
        run = threads.runs.create(
            thread_id=th.id,
            assistant_id=assistant_id,
            tool_resources={"file_search": {"vector_store_ids": [vs_id]}},
        )
    except Exception:
        run = threads.runs.create(thread_id=th.id, assistant_id=assistant_id)

    # Poll for completion (simple loop)
    waited = 0
    interval = 1
    while True:
        r = threads.runs.retrieve(thread_id=th.id, run_id=run.id)
        status = getattr(r, "status", None)
        if status in ("completed", "failed", "cancelled", "expired"):
            break
        await asyncio.sleep(interval)
        waited += interval
        if timeout_s and waited >= timeout_s:
            break

    if status != "completed":
        raise RuntimeError(f"Assistant run not completed (status={status})")

    # Get the latest assistant message
    msgs = threads.messages.list(thread_id=th.id, order="desc", limit=1)
    # Extract text content robustly
    reply_text = ""
    try:
        message = msgs.data[0]
        parts = getattr(message, "content", []) or []
        for p in parts:
            if getattr(p, "type", "") == "text":
                t = getattr(getattr(p, "text", None), "value", None)
                if t:
                    reply_text += t
    except Exception:
        pass

    return reply_text or "I couldn't extract an answer from the knowledge base."
