import os
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from bson import ObjectId
from fastapi import HTTPException

# Minimal env so pydantic Settings can load during imports
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB", "testdb")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_MODEL", "gpt-test")
os.environ.setdefault("JWT_SECRET", "test-secret")

from src.security import deps  # noqa: E402
from src.security.deps import RequestContext  # noqa: E402


class _DummySessions:
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, query):
        return self.doc


class _DummyDB:
    def __init__(self, doc):
        self.sessions = _DummySessions(doc)


class SessionAliveGuardTests(IsolatedAsyncioTestCase):
    def setUp(self):
        sid = str(ObjectId())
        self.ctx = RequestContext(sub="guest", sid=sid, tid="default", role="user", raw={})
        self.oid = ObjectId(self.ctx.sid)

    async def test_allows_timezone_aware_created_at(self):
        created_at = datetime.now(timezone.utc)
        doc = {"_id": self.oid, "status": "active", "created_at": created_at}
        with patch("src.security.deps.get_db", return_value=_DummyDB(doc)):
            await deps.session_alive_guard(self.ctx)

    async def test_rejects_expired_session(self):
        expired_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        doc = {"_id": self.oid, "status": "active", "expires_at": expired_at}
        with patch("src.security.deps.get_db", return_value=_DummyDB(doc)):
            with self.assertRaises(HTTPException) as ctx:
                await deps.session_alive_guard(self.ctx)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "session expired")

    async def test_accepts_naive_created_at_backfill(self):
        created_at = datetime.utcnow()  # naive datetime
        doc = {"_id": self.oid, "status": "active", "created_at": created_at}
        with patch("src.security.deps.get_db", return_value=_DummyDB(doc)):
            await deps.session_alive_guard(self.ctx)
