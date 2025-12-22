# src/feature_modules/file_content/config.py
from __future__ import annotations
import os
from pathlib import Path

# --- Backend selection ---
# "mongo" (default) uses your MongoDB `files` collection to resolve file_id -> absolute path.
# "path"  is a dev fallback that treats file_id as a relative path under FILES_STORAGE_ROOT.
FILES_BACKEND = os.getenv("FILES_BACKEND", "mongo").strip().lower()

# --- Mongo settings (used when FILES_BACKEND = "mongo") ---
MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "app")
FILES_COLLECTION = os.getenv("FILES_COLLECTION", "files")

# --- Path backend settings (used when FILES_BACKEND = "path") ---
FILES_STORAGE_ROOT = Path(os.getenv("FILES_STORAGE_ROOT", os.getcwd())).resolve()
FILES_INDEX_PATH = os.getenv("FILES_INDEX_PATH", "").strip() or None
FILES_FALLBACK_TO_PATH = os.getenv("FILES_FALLBACK_TO_PATH", "true").lower() == "true"

# --- Public access flag (no auth for now, per your decision) ---
# Default to False for production safety; can be enabled explicitly via env.
PUBLIC_BY_ID = os.getenv("FILE_CONTENT_PUBLIC_BY_ID", "false").lower() == "true"
