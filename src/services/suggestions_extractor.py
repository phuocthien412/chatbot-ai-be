from __future__ import annotations
"""
Extract <suggestions>[...]</suggestions> from the tail of an assistant message.

Contract:
- The tag MUST be at the very end of the message (after visible prose).
- Inside the tag must be a JSON array of strings, e.g. ["A", "B"].
- If anything goes wrong, we return (clean_text, []).

We also:
- enforce max 5 items,
- deduplicate while preserving order,
- strip whitespace around suggestions.
"""

from typing import List, Tuple
import json
import re

_SUGG_RX = re.compile(r"<suggestions>(.*?)</suggestions>\s*$", re.DOTALL)

def extract_suggestions(text: str) -> Tuple[str, List[str]]:
    if not isinstance(text, str) or not text:
        return text or "", []

    m = _SUGG_RX.search(text)
    if not m:
        return text, []

    raw_block = m.group(1)
    clean_text = text[: m.start()].rstrip()

    suggestions: List[str] = []
    try:
        data = json.loads(raw_block)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    s = item.strip()
                    if s and s not in suggestions:
                        suggestions.append(s)
                # ignore non-string items
    except Exception:
        # ignore parse errors
        return clean_text, []

    # cap at 5
    if len(suggestions) > 5:
        suggestions = suggestions[:5]

    return clean_text, suggestions
