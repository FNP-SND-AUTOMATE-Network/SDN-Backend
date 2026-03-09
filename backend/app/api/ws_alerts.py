"""
WebSocket Alerts Endpoint — Real-time Alert Broadcasting

Endpoint:
  WS /ws/alerts   —   Next.js (หรือ client อื่น) เชื่อมต่อเพื่อรับ Zabbix alerts แบบ real-time

Frontend Usage (Next.js):
    const ws = new WebSocket("ws://<backend-host>:8000/ws/alerts");
    ws.onmessage = (event) => {
        const alert = JSON.parse(event.data);
        console.log("New alert:", alert);
    };
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.ws_manager import ws_manager
from app.core.logging import logger

router = APIRouter(tags=["WebSocket Alerts"])


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """
    WebSocket endpoint สำหรับรับ Zabbix alert แบบ real-time.

    Flow:
      1. Client connects → accept & register
      2. Keep connection alive (wait for incoming messages / ping-pong)
      3. On disconnect → unregister

    Server จะ broadcast ข้อมูล alert ผ่าน ConnectionManager
    เมื่อ Zabbix webhook POST เข้ามาที่ /api/v1/zabbix/webhook
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # รอ receive เพื่อ keep connection alive
            # Client อาจส่ง ping/pong หรือ message อะไรก็ได้
            # ถ้า client disconnect จะ raise WebSocketDisconnect
            data = await websocket.receive_text()
            # (Optional) log messages from client, e.g. heartbeat
            logger.debug(f"[WS-Alerts] Received from client: {data}")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        logger.info("[WS-Alerts] Client disconnected gracefully")
    except Exception as exc:
        ws_manager.disconnect(websocket)
        logger.error(f"[WS-Alerts] Unexpected error: {exc}")
