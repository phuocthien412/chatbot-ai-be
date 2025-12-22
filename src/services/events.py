from __future__ import annotations
import asyncio
from typing import Dict, Any, Set
from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self.active: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self.active:
                self.active.remove(ws)
        try:
            await ws.close()
        except Exception:
            pass

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self.active)
        if not targets:
            return
        data = payload
        for ws in targets:
            try:
                await ws.send_json(data)
            except Exception:
                await self.disconnect(ws)


manager = WebSocketManager()


async def broadcast_event(event: Dict[str, Any]) -> None:
    """Fire-and-forget friendly broadcast."""
    try:
        await manager.broadcast(event)
    except Exception:
        pass
