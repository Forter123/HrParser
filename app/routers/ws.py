from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime import manager

router = APIRouter()


@router.websocket("/ws/feed")
async def feed_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
