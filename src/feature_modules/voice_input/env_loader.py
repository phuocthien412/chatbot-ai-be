import os
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

_ENV_READY = False

def _load(paths: list[Path]) -> list[str]:
    loaded = []
    if load_dotenv is None:
        return loaded
    for p in paths:
        try:
            if p.exists() and load_dotenv(dotenv_path=p, override=False):
                loaded.append(str(p))
        except Exception:
            pass
    return loaded

def ensure_feature_env(var_names: list[str]) -> None:
    """
    Load feature-local env (voice_input/.env.voice_input) and project root .env
    if any of the requested variables are missing.
    """
    global _ENV_READY
    if all(os.getenv(v) for v in var_names):
        _ENV_READY = True
        return
    if os.getenv("STT_LOAD_DOTENV", "true").lower() == "false":
        _ENV_READY = True
        return

    here = Path(__file__).resolve().parent
    module_env = here / ".env.voice_input"
    # __file__ => .../chatbot-ai-be/src/feature_modules/voice_input/env_loader.py
    # Repo root is parents[3]; parents[4] would jump above the project.
    root_env = Path(__file__).resolve().parents[3] / ".env"

    loaded = _load([module_env, root_env])
    _ENV_READY = True
    if loaded:
        logging.info("voice_input.env_loader loaded env: %s", loaded)
