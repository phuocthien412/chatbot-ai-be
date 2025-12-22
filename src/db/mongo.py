from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional
from ..config import settings

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None

async def connect() -> None:
    """
    Idempotently connect and verify the connection with a ping.
    """
    global _client, _db
    if _client is not None and _db is not None:
        return

    _client = AsyncIOMotorClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=5000,
        tz_aware=False,
    )
    _db = _client[settings.mongodb_db]

    # verify connection (raises if not available)
    await _db.command("ping")

    # indices
    await _db.messages.create_index([("session_id", 1), ("created_at", 1)])
    await _db.sessions.create_index([("last_activity_at", -1)])

async def disconnect() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None

def is_connected() -> bool:
    return _db is not None

def get_db() -> AsyncIOMotorDatabase:
    """
    Non-async getter used inside repos at call time.
    Raises a helpful error if startup didn’t run.
    """
    if _db is None:
        raise RuntimeError(
            "MongoDB is not connected. Ensure app startup calls db.connect() "
            "and that you're running the correct app module."
        )
    return _db
