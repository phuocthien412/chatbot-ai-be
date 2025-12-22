from __future__ import annotations
"""
prompt_loader.py

Loads core + business prompt snippets from /prompts, composes final prompts,
and caches them with a small TTL. Includes a simple reload() to clear cache.

Layout (all files optional except system core):
  /prompts/
    system/
      actor.core.md
      picker.core.md
    business/
      profile.md
      policies.md
      glossary.md
"""

import os
import time

# Root of the prompts directory (env override supported)
_PROMPTS_ROOT = os.environ.get("PROMPTS_ROOT", os.path.join(os.getcwd(), "prompts"))

_TTL_SEC = 30.0

_CACHE = {
    "actor_core": None,
    "picker_core": None,
    "profile": None,
    "policies": None,
    "glossary": None,
    "expires": 0.0,
}


def _now() -> float:
    return time.monotonic()


def _safe_read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""
    except Exception:
        # In case of any read error, return empty (fail-safe)
        return ""


def _refresh_cache_if_needed() -> None:
    if _CACHE["expires"] > _now():
        return

    actor_core = _safe_read(os.path.join(_PROMPTS_ROOT, "system", "actor.core.md"))
    picker_core = _safe_read(os.path.join(_PROMPTS_ROOT, "system", "picker.core.md"))
    profile = _safe_read(os.path.join(_PROMPTS_ROOT, "business", "profile.md"))
    policies = _safe_read(os.path.join(_PROMPTS_ROOT, "business", "policies.md"))
    glossary = _safe_read(os.path.join(_PROMPTS_ROOT, "business", "glossary.md"))

    _CACHE.update(
        {
            "actor_core": actor_core,
            "picker_core": picker_core,
            "profile": profile,
            "policies": policies,
            "glossary": glossary,
            "expires": _now() + _TTL_SEC,
        }
    )


def reload() -> None:
    """Force cache invalidation (used by /admin/prompts/reload)."""
    _CACHE.update(
        {
            "actor_core": None,
            "picker_core": None,
            "profile": None,
            "policies": None,
            "glossary": None,
            "expires": 0.0,
        }
    )


def get_actor_prompt_header() -> str:
    """
    Returns the composed actor *business* header section (excluding capabilities banner,
    which is injected by chat_service). Order:
      [system/actor.core.md]
      [business/profile.md]
      [business/policies.md]
    """
    _refresh_cache_if_needed()
    parts = []
    if _CACHE["actor_core"]:
        parts.append(_CACHE["actor_core"])
    if _CACHE["profile"]:
        parts.append(_CACHE["profile"])
    if _CACHE["policies"]:
        parts.append(_CACHE["policies"])
    return "\n\n".join(parts).strip()


def get_picker_prompt_header() -> str:
    """
    Returns the composed picker *business* header section:
      [system/picker.core.md]
      [business/glossary.md] (helps with synonyms/keywords)
    """
    _refresh_cache_if_needed()
    parts = []
    if _CACHE["picker_core"]:
        parts.append(_CACHE["picker_core"])
    if _CACHE["glossary"]:
        parts.append("\n\n# Glossary / Synonyms\n" + _CACHE["glossary"])
    return "\n\n".join(parts).strip()
