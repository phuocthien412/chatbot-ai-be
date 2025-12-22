# src/feature_modules/file_content/models.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

@dataclass
class FileMeta:
    file_id: str
    abs_path: Path
    original_name: str
    mime: Optional[str]
    size: Optional[int]
    sha256: Optional[str]
