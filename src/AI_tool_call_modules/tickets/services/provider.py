from __future__ import annotations
from typing import List, Dict, Any, Optional

from src.AI_tool_call_modules.base import FeatureProvider
from src.services.dynamic_tools import build_tools_for_type_ids
from src.AI_tool_call_modules.tickets.services.ticket_service import handle_create_ticket
from src.db.mongo import get_db


class TicketsProviderImpl:
    # Core identity / tooling
    capability_id = "tickets.create"
    tool_namespace = "create_ticket__"

    # Picker-friendly metadata
    display_name = "Tạo phiếu"
    target_label = "loại phiếu"
    requires_target = True

    # -------- Picker hooks: list specs by display_name --------
    async def get_picker_targets_minimal(self, db) -> List[Dict[str, str]]:
        """
        Return items like: {"id": "<type_id>", "display_name": "Trả bàn"}
        """
        cur = db.ticket_types.find({}, {"_id": 1, "display_name": 1})
        results = [x async for x in cur]
        return [
            {"id": str(x["_id"]), "display_name": (x.get("display_name") or str(x["_id"])).strip()}
            for x in results
        ]

    def get_continuation_hints(self) -> Dict[str, List[str]]:
        return {"tool_prefixes": [self.tool_namespace], "keywords": ["tạo vé", "phiếu", "điền thông tin"]}

    # -------- Actor surface: tools & tool handling --------
    async def tools_spec(self, session_ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        If a target is chosen, expose create tools for those target_ids.
        If no target yet, expose a single discovery tool to list all ticket types from DB.
        """
        type_ids = session_ctx.get("type_ids") or session_ctx.get("target_ids") or []

        if type_ids:
            return await build_tools_for_type_ids(type_ids)

        # No target chosen yet → provide a discovery tool so actor can ground truth the list
        return [
            {
                "type": "function",
                "function": {
                    "name": "tickets__list_types",
                    "description": (
                        "List all available ticket types from the database. "
                        "Use this when the user asks what tickets are supported or asks to list ticket types."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            }
        ]

    async def handle_tool_call(self, session_id: str, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        # Discovery tool: list all ticket types
        if name == "tickets__list_types":
            db = get_db()
            cur = db.ticket_types.find({}, {"_id": 1, "display_name": 1})
            rows = [x async for x in cur]
            types = [{"id": str(x["_id"]), "display_name": x.get("display_name") or str(x["_id"])} for x in rows]
            return {"ok": True, "types": types, "count": len(types)}

        # Create tools: prefixed with "create_ticket__<type_id>"
        if not name.startswith(self.tool_namespace):
            return {"ok": False, "error": {"code": "UNKNOWN_TOOL"}}
        type_id = name.split(self.tool_namespace, 1)[1] or None
        if not type_id:
            return {"ok": False, "error": {"code": "UNKNOWN_TOOL"}}

        ok, result = await handle_create_ticket(session_id, {"type": type_id, "fields": args})
        if ok:
            return {"ok": True, **result}
        return {"ok": False, "error": result.get("error") or {"code": "CREATE_FAILED"}}

    # -------- Optional banners / legacy hints --------
    def capabilities_banner_chunk(self) -> str:
        return "• Ticketing: dynamic ticket creation (schema validation & file uploads)"

    def actor_prompt_addendum(self) -> Optional[str]:
        return None

    def picker_hint(self, session_ctx: Dict[str, Any]) -> Dict[str, Any]:
        history = session_ctx.get("history") or []
        text_tail = " ".join([(m.get("content") or "") for m in history[-4:] if isinstance(m, dict)]).lower()
        positive_kw = ["tạo phiếu", "tạo vé", "đính kèm", "gửi ảnh", "gửi file", "mẫu đơn", "thông tin bắt buộc"]
        negative_kw = ["tra cứu", "tìm", "giá", "bao nhiêu", "ở đâu", "policy", "tài liệu", "hướng dẫn"]
        cont_markers = ["vui lòng cung cấp", "hãy cung cấp", "thiếu", "còn thiếu", "gửi ảnh", "tải lên"]
        in_progress = any(k in text_tail for k in cont_markers)
        ended = any(
            isinstance(m, dict) and isinstance(m.get("content"), str) and "TOOL:create_ticket" in m["content"]
            for m in history[-10:]
        )
        continuation = "prefer" if (in_progress and not ended) else "neutral"
        return {
            "capability_id": self.capability_id,
            "score_bump": 0.2 if any(k in text_tail for k in positive_kw) and not any(k in text_tail for k in negative_kw) else 0.0,
            "keywords_any": positive_kw,
            "negative_any": negative_kw,
            "continuation": continuation,
            "in_progress": in_progress,
            "end_markers": ["xong", "hoàn tất", "hoàn thành", "đã tạo vé", "đã tạo phiếu"],
        }


# Export singleton
provider: FeatureProvider = TicketsProviderImpl()
