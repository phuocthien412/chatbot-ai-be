from __future__ import annotations
from fastapi import APIRouter, WebSocket
from src.security.jwt import verify_jwt
from src.services.user_events import user_ws_manager

router = APIRouter(prefix="/ws", tags=["ws"])


@router.websocket("/user")
async def user_ws(websocket: WebSocket):
    """
    User WebSocket. Requires ?token=<user JWT with sid>.
    Supports optional ping/pong (client can send "ping").
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    try:
        payload = verify_jwt(token)
        session_id = payload.get("sid")
        if not session_id:
            await websocket.close(code=4401)
            return
    except Exception:
        await websocket.close(code=4401)
        return

    await user_ws_manager.connect(session_id, websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                try:
                    await websocket.send_text("pong")
                except Exception:
                    break
    except Exception:
        await user_ws_manager.disconnect(session_id, websocket)
