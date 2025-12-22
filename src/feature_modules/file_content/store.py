# src/feature_modules/file_content/store.py
from __future__ import annotations
from typing import Optional

from .config import FILES_BACKEND
from .models import FileMeta

if FILES_BACKEND == "mongo":
    from .backends.mongo_store import lookup as backend_lookup
else:
    from .backends.path_store import lookup as backend_lookup

class FileIndex:
    async def lookup(self, file_id: str) -> Optional[FileMeta]:
        return await backend_lookup(file_id)

file_index = FileIndex()
