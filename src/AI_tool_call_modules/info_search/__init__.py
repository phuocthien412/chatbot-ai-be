# src/AI_tool_call_modules/info_search/__init__.py
"""
Info Search (one-home module)

Importing this package will:
- Register the provider with features_registry (via provider's side-effect)
- Make the FastAPI router importable
"""

# ✅ Import provider so its module-level _register(provider) runs
from .provider import provider as _provider  # noqa: F401

# Optional: re-export router for convenience (not required by main.py)
from .routes import router  # noqa: F401
