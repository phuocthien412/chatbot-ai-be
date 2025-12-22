# Task proposals

## Fix a typo
- Correct the greeting in `prompts/business/profile.md` where the question currently reads "What can i help you today?" so that the assistant introduces itself with proper capitalization and grammar.

## Fix a bug
- Harden `session_alive_guard` in `src/security/deps.py` so that a non-integer `JWT_TTL_SECONDS` environment variable does not trigger a 500 when `int(settings.jwt_ttl_seconds)` raises; fall back to the default TTL like `_ttl_seconds()` instead.

## Fix a documentation discrepancy
- Update `docs/CONTRIBUTING_NewFeature.md` to point contributors at the actual `src/feature_modules/<feature_id>/` structure used in the codebase instead of the outdated `src/modules/<feature_id>/` paths.

## Improve a test
- Add coverage for `enforce_sid_binding` in `src/security/deps.py` to assert that requests supplying a mismatched `session_id` are rejected with a 403 for both JSON and form-data payloads, preventing regression in session binding enforcement.
