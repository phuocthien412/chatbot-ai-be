from __future__ import annotations
import asyncio
from typing import Dict, Set, Any
from fastapi import WebSocket


class SessionWebSocketManager:
    def __init__(self) -> None:
        self.connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            if session_id not in self.connections:
                self.connections[session_id] = set()
            self.connections[session_id].add(ws)

    async def disconnect(self, session_id: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self.connections.get(session_id)
            if conns and ws in conns:
                conns.remove(ws)
            if conns is not None and len(conns) == 0:
                self.connections.pop(session_id, None)
        try:
            await ws.close()
        except Exception:
            pass

    async def broadcast(self, session_id: str, payload: Dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self.connections.get(session_id, []))
        if not targets:
            return
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                await self.disconnect(session_id, ws)


user_ws_manager = SessionWebSocketManager()


async def broadcast_to_user(session_id: str, payload: Dict[str, Any]) -> None:
    """Fire-and-forget friendly broadcast to the given session's user."""
    try:
        await user_ws_manager.broadcast(session_id, payload)
    except Exception:
        pass
