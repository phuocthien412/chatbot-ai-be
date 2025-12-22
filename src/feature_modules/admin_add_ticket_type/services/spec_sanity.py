from __future__ import annotations
"""
Light sanity checks for a generated ticket-type spec (Phase 1).

We expect:
{
  "fields": [
    {
      "key": "name",
      "type": "string|integer|number|boolean|enum|date|phone|email|file",
      "required": true|false,
      ...optional constraints...
    }
  ],
  "i18n": { ... }   # optional
}
"""

from typing import Dict, Any, List, Set
import re

SUPPORTED_TYPES = {"string", "integer", "number", "boolean", "enum", "date", "phone", "email", "file"}

def basic_spec_checks(spec: Dict[str, Any]) -> List[str]:
    errs: List[str] = []

    if not isinstance(spec, dict):
        return ["spec must be an object"]

    fields = spec.get("fields")
    if not isinstance(fields, list) or not fields:
        return ["spec.fields must be a non-empty array"]

    seen: Set[str] = set()
    for idx, f in enumerate(fields):
        if not isinstance(f, dict):
            errs.append(f"fields[{idx}] must be an object")
            continue

        key = f.get("key")
        ftype = f.get("type")

        if not key or not isinstance(key, str):
            errs.append(f"fields[{idx}].key must be a non-empty string")
            continue

        if key in seen:
            errs.append(f"duplicate field key '{key}'")
        seen.add(key)

        if ftype not in SUPPORTED_TYPES:
            errs.append(f"{key}: type '{ftype}' not in {sorted(SUPPORTED_TYPES)}")

        # enum rules
        if ftype == "enum":
            enum = f.get("enum")
            if not isinstance(enum, list) or not enum or not all(isinstance(x, str) for x in enum):
                errs.append(f"{key}: enum must be a non-empty list of strings")

        # string length consistency
        min_len = f.get("minLength")
        max_len = f.get("maxLength")
        if isinstance(min_len, int) and isinstance(max_len, int) and min_len > max_len:
            errs.append(f"{key}: minLength > maxLength")

        # number bounds
        minimum = f.get("minimum")
        maximum = f.get("maximum")
        if (isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)) and minimum > maximum):
            errs.append(f"{key}: minimum > maximum")

        # pattern validity
        pattern = f.get("pattern")
        if pattern:
            try:
                re.compile(pattern)
            except re.error as e:
                errs.append(f"{key}: invalid regex: {e}")

        # file accept list
        if ftype == "file":
            acc = f.get("accept")
            if not isinstance(acc, list) or not acc or not all(isinstance(x, str) for x in acc):
                errs.append(f"{key}: file.accept must be a non-empty list of strings")

        # inject sensible defaults (non-fatal)
        if ftype == "phone" and not f.get("pattern"):
            f["pattern"] = r"^(?:\+84|0)\d{9,10}$"

    return errs
