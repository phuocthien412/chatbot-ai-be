# src/feature_modules/file_content/appdb.py
from __future__ import annotations

import asyncio
import importlib
import inspect
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConfigurationError


async def _maybe_await(obj):
    if inspect.isawaitable(obj):
        return await obj
    return obj


def _import_first(*module_paths: str) -> Optional[Any]:
    for mp in module_paths:
        try:
            return importlib.import_module(mp)
        except Exception:
            continue
    return None


async def get_app_database() -> AsyncIOMotorDatabase:
    """
    Try very hard to return the SAME AsyncIOMotorDatabase your app uses.
    Import patterns covered (in order):

    1) Relative package import from this feature: src.db.mongo
       - exports: get_db() or database / db / motor_db / client+settings

    2) Absolute variants if package name differs:
       - db.mongo
       - app.db.mongo
       - AI_chatbot_with_KG.src.db.mongo   # defensive, in case of unusual names

    Fallback: if nothing found, create a new client from MONGO_URI/MONGO_DB_NAME
    (but the main goal is to reuse the app's own handle).
    """
    # Try the most likely modules first (relative to 'src')
    mod = _import_first(
        "src.db.mongo",
        "db.mongo",
        "app.db.mongo",
        "AI_chatbot_with_KG.src.db.mongo",
    )
    if mod:
        # 1) get_db() coroutine or function
        get_db = getattr(mod, "get_db", None) or getattr(mod, "get_database", None)
        if callable(get_db):
            db = await _maybe_await(get_db())
            if isinstance(db, AsyncIOMotorDatabase):
                return db

        # 2) exported database object
        for attr in ("database", "db", "motor_db"):
            obj = getattr(mod, attr, None)
            if isinstance(obj, AsyncIOMotorDatabase):
                return obj

        # 3) client + settings
        client = getattr(mod, "client", None) or getattr(mod, "motor_client", None)
        if isinstance(client, AsyncIOMotorClient):
            # Try to get default DB or infer from settings
            try:
                return client.get_default_database()
            except ConfigurationError:
                pass

            # Inspect a 'settings' object for db name if present
            settings = getattr(mod, "settings", None)
            db_name = None
            if settings is not None:
                db_name = getattr(settings, "MONGO_DB_NAME", None) or getattr(settings, "mongo_db_name", None)
            if db_name:
                return client[db_name]

    # --- Fallback: use env-driven client (kept very defensive) ---
    # We import the feature's config only now to avoid interfering with your Pydantic Settings.
    from .config import MONGO_URI, MONGO_DB_NAME  # type: ignore
    client = AsyncIOMotorClient(MONGO_URI)
    try:
        db = client.get_default_database()
        return db
    except ConfigurationError:
        pass
    db_name = MONGO_DB_NAME or "app"
    return client[db_name]
