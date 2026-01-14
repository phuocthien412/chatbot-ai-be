from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from fastapi import HTTPException

from src.db.mongo import get_db
from src.security.deps import RequestContext

DEFAULT_ROLES: List[dict] = [
    {"id": "super_admin", "label": "Super Admin", "description": "Full system access"},
    {"id": "admin", "label": "Admin", "description": "System administration"},
    {"id": "owner", "label": "Owner", "description": "Project owner"},
    {"id": "dev", "label": "DEV", "description": "Developer access"},
    {"id": "user", "label": "User", "description": "End user"},
]

MODULE_ACTIONS = {
    "dashboard": ["view"],
    "conversations": ["view", "reply", "handoff", "delete"],
    "prompts": ["view", "edit", "reload"],
    "ticket_types": ["view", "create", "edit", "delete"],
    "knowledge_base": ["view", "upload", "delete", "refresh"],
    "settings": ["view", "edit"],
    "debug": ["view", "run"],
    "profile": ["view", "edit"],
    "users": ["view", "create", "edit", "delete", "assign_role", "change_password"],
    "permissions": ["view", "edit"],
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def build_default_permissions() -> Dict[str, Dict[str, Dict[str, bool]]]:
    permissions: Dict[str, Dict[str, Dict[str, bool]]] = {}

    for role in [r["id"] for r in DEFAULT_ROLES]:
        permissions[role] = {}
        for module, actions in MODULE_ACTIONS.items():
            permissions[role][module] = {action: False for action in actions}

    for module, actions in MODULE_ACTIONS.items():
        permissions["super_admin"][module] = {action: True for action in actions}

    for module, actions in MODULE_ACTIONS.items():
        permissions["admin"][module] = {action: True for action in actions}
    permissions["admin"]["permissions"]["edit"] = False

    for action in MODULE_ACTIONS["dashboard"]:
        permissions["owner"]["dashboard"][action] = True
    for action in MODULE_ACTIONS["conversations"]:
        permissions["owner"]["conversations"][action] = True
    for action in MODULE_ACTIONS["prompts"]:
        permissions["owner"]["prompts"][action] = True
    for action in MODULE_ACTIONS["ticket_types"]:
        permissions["owner"]["ticket_types"][action] = True
    for action in MODULE_ACTIONS["knowledge_base"]:
        permissions["owner"]["knowledge_base"][action] = True
    permissions["owner"]["settings"]["view"] = True
    permissions["owner"]["debug"]["view"] = True
    for action in MODULE_ACTIONS["profile"]:
        permissions["owner"]["profile"][action] = True
    permissions["owner"]["permissions"]["view"] = True

    permissions["dev"]["settings"]["view"] = True
    permissions["user"]["dashboard"]["view"] = True

    return permissions


async def get_permissions_map() -> Dict[str, Dict[str, Dict[str, bool]]]:
    db = get_db()
    doc = await db.admin_permissions.find_one({"_id": "global"})
    if not doc or not doc.get("permissions"):
        return build_default_permissions()
    return doc["permissions"]


async def ensure_permission(ctx: RequestContext, module: str, action: str) -> None:
    permissions = await get_permissions_map()
    role = ctx.role or ""
    allowed = permissions.get(role, {}).get(module, {}).get(action, False)
    if not allowed:
        raise HTTPException(status_code=403, detail="Permission denied")
