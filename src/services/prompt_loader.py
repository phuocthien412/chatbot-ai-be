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
import re
import time
from typing import Optional

from src.services.language_utils import language_directive, normalize_language

# Root of the prompts directory (env override supported)
_PROMPTS_ROOT = os.environ.get("PROMPTS_ROOT", os.path.join(os.getcwd(), "prompts"))
_VERSIONS_DIR = os.path.join(_PROMPTS_ROOT, ".versions")

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

def _latest_versioned_path(name: str) -> Optional[str]:
    try:
        entries = os.listdir(_VERSIONS_DIR)
    except FileNotFoundError:
        return None

    pattern = re.compile(rf"^{re.escape(name)}-v(\d+)-(\d{{4}}-\d{{2}}-\d{{2}})\.md$")
    latest_version = None
    latest_path = None
    for filename in entries:
        match = pattern.match(filename)
        if not match:
            continue
        version = int(match.group(1))
        if latest_version is None or version > latest_version:
            latest_version = version
            latest_path = os.path.join(_VERSIONS_DIR, filename)
    return latest_path

def _read_business_prompt(name: str) -> str:
    latest_path = _latest_versioned_path(name)
    if latest_path:
        return _safe_read(latest_path)
    return _safe_read(os.path.join(_PROMPTS_ROOT, "business", f"{name}.md"))


def _refresh_cache_if_needed() -> None:
    if _CACHE["expires"] > _now():
        return

    actor_core = _safe_read(os.path.join(_PROMPTS_ROOT, "system", "actor.core.md"))
    picker_core = _safe_read(os.path.join(_PROMPTS_ROOT, "system", "picker.core.md"))
    profile = _read_business_prompt("profile")
    policies = _read_business_prompt("policies")
    glossary = _read_business_prompt("glossary")

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


def _language_block(language: Optional[str]) -> str:
    directive = language_directive(language)
    if not directive:
        return ""
    return "## Language\n" + directive


def get_actor_prompt_header(language: Optional[str] = None) -> str:
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
    lang = normalize_language(language)
    lang_block = _language_block(lang)
    if lang_block:
        parts.append(lang_block)
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
