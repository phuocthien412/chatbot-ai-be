from __future__ import annotations
"""admin_users_repo.py — CRUD helpers for the `admin_users` collection.

Schema (collection: admin_users)
- _id: ObjectId
- email: str (unique, lowercased)
- display_name: str
- password_hash: str (format: "pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>")
- roles: list[str]
- is_active: bool
- created_at: datetime (UTC)
- updated_at: datetime (UTC)
- last_login_at: datetime (UTC) | None
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import os
import hashlib
import hmac

from bson import ObjectId

from src.db.mongo import get_db


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256.

    Returns a portable string representation:
        pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
    """
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    salt = os.urandom(16)
    iterations = 200_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored PBKDF2-SHA256 hash string."""
    try:
        scheme, iter_str, salt_hex, hash_hex = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


def _to_oid(id_value: Any) -> Optional[ObjectId]:
    if isinstance(id_value, ObjectId):
        return id_value
    try:
        return ObjectId(str(id_value))
    except Exception:
        return None


async def get_admin_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Fetch an admin user by email (case-insensitive)."""
    db = get_db()
    normalized = _normalize_email(email)
    doc = await db.admin_users.find_one({"email": normalized})
    return doc


async def create_admin_user(
    email: str,
    password: str,
    display_name: Optional[str] = None,
    roles: Optional[List[str]] = None,
    is_active: bool = True,
) -> Dict[str, Any]:
    """Create a new admin user.

    This is primarily intended for seeding via a script or shell.

    Example seeding snippet:

        from src.repositories.admin_users_repo import create_admin_user
        await create_admin_user("admin@example.com", "SuperSecret123!")

    """
    db = get_db()
    normalized = _normalize_email(email)
    now = _now_utc()
    pwd_hash = hash_password(password)
    doc: Dict[str, Any] = {
        "email": normalized,
        "display_name": display_name or normalized,
        "password_hash": pwd_hash,
        "roles": roles or ["admin"],
        "is_active": is_active,
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
    }
    res = await db.admin_users.insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


async def mark_login_success(admin_id: Any) -> None:
    """Update last_login_at for an admin user after successful login."""
    db = get_db()
    oid = _to_oid(admin_id)
    if oid is None:
        return
    now = _now_utc()
    await db.admin_users.update_one(
        {"_id": oid},
        {"$set": {"last_login_at": now, "updated_at": now}},
    )
