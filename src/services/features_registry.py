from __future__ import annotations

from typing import Dict, Optional, List
import logging

from src.AI_tool_call_modules.base import FeatureProvider

log = logging.getLogger(__name__)

# Internal registry (capability_id -> provider)
_REGISTRY: Dict[str, FeatureProvider] = {}


# ---- Registration API ------------------------------------------------------ #

def register(provider: FeatureProvider) -> bool:
    """
    Add a provider instance to the registry.

    Returns:
        True if registered, False if skipped (invalid or duplicate).
    """
    if provider is None:
        log.warning("feature_registry.register: provider is None; skipping")
        return False

    capability_id = getattr(provider, "capability_id", None)
    if not isinstance(capability_id, str) or not capability_id.strip():
        log.error("feature_registry.register: provider missing valid capability_id; skipping")
        return False

    if capability_id in _REGISTRY:
        log.warning(
            "feature_registry.register: duplicate capability_id '%s'; existing kept, new skipped",
            capability_id,
        )
        return False

    _REGISTRY[capability_id] = provider
    log.info("Feature provider registered: %s", capability_id)
    return True


def _safe_import_and_register(import_callable, name: str) -> None:
    """
    Import provider lazily inside a try/except so a single broken feature
    can't crash app startup.
    """
    try:
        provider = import_callable()
        register(provider)
    except Exception as e:  # pragma: no cover
        log.exception("feature_registry: skipping provider '%s' due to init error: %s", name, e)


def register_default_providers() -> None:
    """
    Import and register the built-in providers.
    Add new ones here by following the same pattern.
    """
    def _import_tickets():
        from src.AI_tool_call_modules.tickets.services.provider import provider as tickets_provider
        return tickets_provider

    _safe_import_and_register(_import_tickets, "tickets")

    # def _import_info_search():
    #     from src.AI_tool_call_modules.info_search.services.provider import provider as info_search_provider
    #     return info_search_provider

    # _safe_import_and_register(_import_info_search, "info_search")


# ---- Query API ------------------------------------------------------------- #

def get_provider(capability_id: str) -> Optional[FeatureProvider]:
    return _REGISTRY.get(capability_id)


def all_providers() -> List[FeatureProvider]:
    # Stable order by capability_id so downstream UI is deterministic
    return [_REGISTRY[k] for k in sorted(_REGISTRY.keys())]


def all_capability_ids() -> List[str]:
    return sorted(_REGISTRY.keys())


# ---- Test helpers (optional) ---------------------------------------------- #

def _reset_registry_for_tests() -> None:
    """Clear the registry. Use in unit tests only."""
    _REGISTRY.clear()


# ---- Eager default registration (preserve previous behavior) -------------- #

# Previously, providers were imported and registered at module import time.
# To keep that DX while improving safety, we now do a guarded registration here.
register_default_providers()
