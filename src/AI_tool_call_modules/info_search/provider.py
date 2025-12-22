from __future__ import annotations
from typing import List, Dict, Any, Optional

from openai import OpenAI
from src.config import settings
from src.db.mongo import get_db
from src.AI_tool_call_modules.base import FeatureProvider
from src.services.features_registry import register as _register

from .service_openai import (
    list_vector_store_files,
    assistants_rag_answer,
)

COL_TENANTS = "info_search_tenants"

class InfoSearchProviderImpl(FeatureProvider):
    """
    KB-only answering:
    - For any factual/doc/policy/company-info type question, the actor MUST call this tool.
    - If the KB has no answer, the assistant must say it doesn't know and suggest uploading or specifying a source.
    - Ticket creation flow remains unaffected (different capability/provider).
    """
    capability_id = "info.search"
    tool_namespace = "info_search__"
    display_name = "Tra cứu thông tin"
    description = "Answer strictly from internal knowledge base with natural citations."

    # If your actor honors this, it will force the function tool call
    force_tool_name = "info_search__answer"

    def capabilities_banner_chunk(self) -> str:
        return "• Info Search: strictly answer from the internal KB (no outside knowledge), with natural citations."

    def actor_prompt_addendum(self) -> Optional[str]:
        # Strong rules so the model NEVER answers from general/world knowledge
        return (
            "KB-ONLY POLICY:\n"
            "• You must NOT use outside knowledge. Do not guess. Do not rely on world knowledge.\n"
            "• For factual/policy/document/company-info questions, you MUST call the tool `info_search__answer` BEFORE attempting any answer.\n"
            "• If the KB returns no relevant sources, reply: you don't have this info yet and suggest what to upload or where to look.\n"
        )

    async def tools_spec(self, session_ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": f"{self.tool_namespace}answer",
                    "description": "Search the internal knowledge base and draft an answer with natural citations.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The user's question needing KB lookup."
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    async def handle_tool_call(self, session_id: str, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name != f"{self.tool_namespace}answer":
            return {"ok": False, "error": {"code": "UNKNOWN_TOOL"}}

        query = (args or {}).get("query", "").strip()
        if not query:
            return {"ok": False, "error": {"code": "EMPTY_QUERY"}}

        # Resolve tenant (extend if you add multi-tenant context later)
        tenant_id = "default"
        db = get_db()
        row = await db[COL_TENANTS].find_one({"tenant_id": tenant_id})
        if not row or not row.get("vector_store_id"):
            return {"ok": False, "error": {"code": "NO_VECTOR_STORE", "hint": "Create/link a vector store and upload docs first."}}
        vs_id = row["vector_store_id"]

        # Guard against empty store (prevents 'clever' non-KB answers)
        client = OpenAI(api_key=settings.openai_api_key)
        try:
            files = list_vector_store_files(client, vs_id)
            if not getattr(files, "data", []):
                return {"ok": False, "error": {"code": "EMPTY_STORE", "hint": "The linked vector store has no files."}}
        except Exception as e:
            return {"ok": False, "error": {"code": "LIST_FILES_FAILED", "detail": str(e)}}

        # Clear instruction for the final answer style (still KB-only)
        system_hint = (
            "Use the internal knowledge base via file_search ONLY. "
            "Do not use outside knowledge. If no relevant sources, say you don't have this info yet and suggest what to upload. "
            "When you do answer, weave source titles naturally and end with 'Sources:'."
        )
        prompt_text = f"{system_hint}\n\nQuestion: {query}"

        try:
            reply_text = await assistants_rag_answer(
                client=client,
                tenant_id=tenant_id,
                vs_id=vs_id,
                model_name=settings.openai_model,
                prompt_text=prompt_text,
                timeout_s=getattr(settings, 'request_timeout_seconds', 60),
            )
        except Exception as e:
            return {"ok": False, "error": {"code": "OPENAI_ERROR", "detail": f"assistants path: {e}"}}

        # If the assistant responded but didn't include any text (edge-case), ensure a KB-only fallback message.
        reply_text = reply_text.strip() or "Mình chưa có thông tin này trong tài liệu nội bộ. Bạn có thể tải lên tài liệu liên quan để mình tra cứu giúp nhé."
        return {"ok": True, "reply_markdown": reply_text, "vector_store_id": vs_id}

    def picker_hint(self, session_ctx: Dict[str, Any]) -> Dict[str, Any]:
        # Strongly encourage the picker to choose this provider for any KB-sounding query.
        history = session_ctx.get("history") or []
        tail = " ".join([m.get("content", "") or "" for m in history[-3:]]).lower()
        positives = [
            # Vietnamese + English cues that signal a factual / company / doc query
            "tra cứu", "tìm kiếm", "tìm", "search", "thông tin", "faq",
            "policy", "quy định", "hướng dẫn", "document", "tài liệu", "văn bản",
            "kb", "knowledge", "file", "pdf", "company", "công ty", "dịch vụ", "aitc"
        ]
        negatives = [
            # Keep ticket creation unaffected
            "tạo phiếu", "tạo vé", "create ticket", "mở ticket"
        ]

        score = 0.85 if any(k in tail for k in positives) and not any(k in tail for k in negatives) else 0.0
        return {
            "capability_id": self.capability_id,
            "score_bump": score,
            "keywords_any": positives,
            "negative_any": negatives,
            "continuation": "neutral",
            "in_progress": False,
            "end_markers": [],
        }

# Export + auto-register with your features registry
provider: FeatureProvider = InfoSearchProviderImpl()
try:
    _register(provider)
except Exception:
    pass
