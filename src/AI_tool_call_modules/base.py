from __future__ import annotations
from typing import Protocol, List, Dict, Any, Optional

class FeatureProvider(Protocol):
    capability_id: str                     # e.g., "tickets.create"
    tool_namespace: str                    # e.g., "create_ticket__"

    def capabilities_banner_chunk(self) -> str:
        """One-liner for the banner (optional)."""
        return ""

    def actor_prompt_addendum(self) -> Optional[str]:
        """Optional extra guidance appended to actor.system."""
        return None

    async def tools_spec(self, session_ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Return OpenAI tool specs for this turn.
        session_ctx may include {'session_id', 'type_ids', 'history'} depending on caller.
        """
        ...

    async def handle_tool_call(
        self, session_id: str, name: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool call and return a JSONable result.
        Must include {'ok': bool, ...}.
        """
        ...

    def picker_hint(self, session_ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Lightweight routing signals from this feature (MVP).
        Example keys:
          - capability_id (str)
          - score_bump (float)
          - keywords_any (List[str])
          - negative_any (List[str])
          - continuation: "prefer" | "neutral" | "forbid"
          - in_progress (bool)
          - end_markers (List[str])
        """
        return {"capability_id": getattr(self, "capability_id", "")}
