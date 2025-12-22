# New Feature Contributor Guide (Drop-in)

## Goal
Add a new feature by creating a folder, writing one provider, and registering it.

## Steps (≤15 minutes)

1) Create a folder:
   `src/modules/<feature_id>/`

2) Implement a provider at:
   `src/modules/<feature_id>/services/provider.py`

   Contract (minimal):
   - `feature_id: str`
   - `version: str`
   - `get_picker_hints(ctx) -> list[str] | None`
   - `get_tools_for_turn(ctx) -> list[dict]`
   - `handle_tool_call(name: str, args: dict, ctx) -> dict`
   - (optional) `banner_fragments(ctx) -> list[str]`
   - (optional) `admin_routes()`

3) Register it in:
   `src/services/features_registry.py`
   ```python
   from src.modules.<feature_id>.services.provider import Provider as <FeatureId>Provider
   REGISTERED_PROVIDERS.append(<FeatureId>Provider())


src/modules/<feature_id>/
  __init__.py
  services/
    __init__.py
    provider.py
  prompts/            # optional (feature-specific business copy)
    profile.md
    examples.md
  routes/             # optional (admin/debug endpoints)
    feature_debug.py
  README.md           # brief: purpose, tools, routes
tests/unit/modules/<feature_id>/test_provider_contract.py
