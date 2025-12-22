from __future__ import annotations
"""
Phase 1 admin endpoints:
- POST /admin/ticket-types/from-text  -> generate spec from description, save both
- GET  /admin/ticket-types-simple     -> list all
- GET  /admin/ticket-types-simple/{id}-> get one

No approval/activation/versioning in this phase.
"""

from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any
from datetime import datetime, timezone

from ....db.mongo import get_db
from ..services.type_gen_simple import generate_spec_from_text
from ..services.spec_sanity import basic_spec_checks
from ....services.notifications import log_notification

router = APIRouter(prefix="/admin", tags=["admin-simple"])

@router.post("/ticket-types/from-text")
async def create_or_replace_from_text(payload: Dict[str, Any] = Body(...)):
    """
    Body:
    {
      "id": "water_leak",
      "display_name": "Báo rò rỉ nước",
      "description_text": "Required: name, VN phone, issue <=3000. Optional: urgency low|normal|high."
    }
    """
    type_id = payload.get("id")
    if not type_id or not isinstance(type_id, str):
        raise HTTPException(400, "id is required")
    display_name = payload.get("display_name")
    description_text = payload.get("description_text") or ""
    if not isinstance(description_text, str) or not description_text.strip():
        raise HTTPException(400, "description_text must be a non-empty string")

    # 1) Ask LLM to generate a spec
    gen = generate_spec_from_text(description_text)
    spec = gen["spec"]
    llm_meta = gen["llm"]
    raw = gen["raw"]

    # 2) Light sanity checks
    errors = basic_spec_checks(spec)
    if errors:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_SPEC",
            "errors": errors,
            "raw": raw[:2000]  # help debug without flooding response
        })

    # 3) Upsert into Mongo
    db = get_db()
    now = datetime.now(timezone.utc)
    doc = {
        "_id": type_id,
        "display_name": display_name,
        "description_text": description_text,
        "spec": spec,
        "llm": llm_meta,
        "timestamps": {"updated_at": now, "created_at": now}
    }
    # If exists, preserve created_at
    existing = await db.ticket_types.find_one({"_id": type_id})
    if existing and existing.get("timestamps", {}).get("created_at"):
        created_at = existing["timestamps"]["created_at"]
        if isinstance(created_at, datetime) and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        doc["timestamps"]["created_at"] = created_at

    await db.ticket_types.update_one({"_id": type_id}, {"$set": doc}, upsert=True)

    # 4) Return the stored doc (without internal ObjectId)
    stored = await db.ticket_types.find_one({"_id": type_id}, {"_id": 1, "display_name": 1, "description_text": 1, "spec": 1, "llm": 1, "timestamps": 1})
    await log_notification(
        title="Ticket type saved",
        message=f"Ticket type '{display_name or type_id}' was created/updated.",
        type_="success",
        module="ticket-types",
        target_name=type_id,
        meta={"display_name": display_name},
    )
    return {"ok": True, "ticket_type": stored}

@router.get("/ticket-types-simple")
async def list_ticket_types_simple():
    db = get_db()
    cur = db.ticket_types.find({}, {"_id": 1, "display_name": 1, "description_text": 1, "timestamps": 1})
    return [x async for x in cur]

@router.get("/ticket-types-simple/{type_id}")
async def get_ticket_type_simple(type_id: str):
    db = get_db()
    doc = await db.ticket_types.find_one(
        {"_id": type_id},
        {"_id": 1, "display_name": 1, "description_text": 1, "spec": 1, "llm": 1, "timestamps": 1}
    )
    if not doc:
        raise HTTPException(404, "Not found")
    return doc
