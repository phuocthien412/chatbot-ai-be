from __future__ import annotations
"""
capabilities_banner.py

Hybrid Capabilities Banner for the actor system prompt:
- Dynamic: reads ticket types from DB (id + display_name), summarizes count and a few names
- Static: other capabilities remain hard-coded one-liners
"""

from typing import List, Tuple
from time import monotonic

from src.db.mongo import get_db

# ---- Static capabilities (keep light; names only, no schemas) ---------------
# You can edit this list anytime to expose more high-level abilities.
STATIC_CAPABILITIES: List[Tuple[str, str]] = [

]

# ---- Banner config -----------------------------------------------------------
_TTL_SEC = 30.0              # refresh dynamic section every 30s
_MAX_TYPE_NAMES = 20          # show at most 4 ticket type names in banner
_CACHE_TEXT = ""
_CACHE_EXPIRES = 0.0


def _now() -> float:
    return monotonic()


async def _dynamic_tickets_phrase() -> str:
    """
    Returns a compact phrase for tickets.create:
      - count of ticket types
      - up to _MAX_TYPE_NAMES display names as examples

    Example: tickets.create (tạo vé hỗ trợ, 5 loại: "Báo rò rỉ nước", "Sửa máy lạnh", …)
    """
    db = get_db()
    cur = db.ticket_types.find({}, {"_id": 1, "display_name": 1}).sort("_id", 1)
    types = [x async for x in cur]

    n = len(types)
    if n == 0:
        # Still mention capability but with no examples
        return "tickets.create (support tickets)"

    # pick up to _MAX_TYPE_NAMES exemplar names
    names: List[str] = []
    for t in types[:_MAX_TYPE_NAMES]:
        name = t.get("display_name") or t["_id"]
        names.append(f"\"{name}\"")

    # ellipsis if more than shown
    examples = ", ".join(names)
    if n > _MAX_TYPE_NAMES:
        examples = f"{examples}, …"

    return f"tickets.create (support tickets, {n} types: {examples})"


def _static_caps_phrase() -> str:
    return "; ".join([f"{k} ({v})" for k, v in STATIC_CAPABILITIES])


async def get_capabilities_banner_text() -> str:
    """
    Returns the full banner text, cached briefly.
    Example:
      Khả năng hệ thống: tickets.create (tạo vé hỗ trợ, 5 loại: "Báo rò rỉ nước", "Sửa máy lạnh", …); knowledge.search (tìm câu trả lời/FAQ); ...
      Nếu yêu cầu vượt ngoài các công cụ hiện diện trong lượt này, hãy hỏi 1 câu ngắn để xác nhận và chuyển đúng khả năng ở lượt sau. Không tự bịa công cụ; không gọi công cụ không có.
    """
    global _CACHE_TEXT, _CACHE_EXPIRES
    if _CACHE_TEXT and _CACHE_EXPIRES > _now():
        return _CACHE_TEXT

    tickets_phrase = await _dynamic_tickets_phrase()
    static_phrase = _static_caps_phrase()

    caps = "; ".join([tickets_phrase, static_phrase]) if static_phrase else tickets_phrase
    banner = (
        f"System capabilities: {caps}. "
        "If a request is outside the tools available in THIS turn, ask a short clarifying question and route correctly in the next turn. "
        "Do not invent tools; do not call tools that are not provided."
    )

    _CACHE_TEXT = banner
    _CACHE_EXPIRES = _now() + _TTL_SEC
    return banner
