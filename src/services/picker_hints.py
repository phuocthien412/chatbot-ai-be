from __future__ import annotations
from typing import Dict, Any
from src.services.features_registry import all_providers

# Tiny scoring knobs (tune later as you like)
ALPHA = 0.25  # positive keywords
BETA  = 0.35  # negative keywords
GAMMA = 0.8   # continuation prefer

def _score_for(hint: Dict[str, Any], text_tail: str) -> float:
    score = float(hint.get("score_bump") or 0.0)
    kws = [k.lower() for k in hint.get("keywords_any") or []]
    nk  = [k.lower() for k in hint.get("negative_any") or []]
    if any(k in text_tail for k in kws): score += ALPHA
    if any(k in text_tail for k in nk): score -= BETA
    if hint.get("in_progress") and (hint.get("continuation") == "prefer"): score += GAMMA
    return score

def collect_picker_hints(session_ctx: Dict[str, Any]) -> Dict[str, Any]:
    history = session_ctx.get("history") or []
    text_tail = " ".join([(m.get("content") or "") for m in history[-4:] if isinstance(m, dict)]).lower()

    hints = []
    for p in all_providers():
        try:
            h = p.picker_hint({"history": history})
            h["__score"] = _score_for(h, text_tail)
            hints.append(h)
        except Exception:
            continue

    if not hints:
        return {"top_capability": None, "rationale": "no hints"}

    hints.sort(key=lambda x: x.get("__score", 0.0), reverse=True)
    top = hints[0]
    return {
        "top_capability": top.get("capability_id"),
        "top_score": top.get("__score", 0.0),
        "all": hints,
    }
