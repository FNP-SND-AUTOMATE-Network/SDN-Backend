"""
WebSocket Connection Manager
จัดการการเชื่อมต่อ WebSocket สำหรับส่งข้อมูลแบบ Real-time ไปยัง Frontend

หน้าที่หลัก:
- รับการเชื่อมต่อจาก Frontend Clients (connect/disconnect)
- Broadcast ข้อมูลแจ้งเตือน (Alert) ไปยังทุก Client ที่เชื่อมต่ออยู่
- เก็บประวัติข้อมูลที่ส่งล่าสุดไว้ใน buffer (สำหรับ Client ที่เพิ่งเชื่อมต่อ)
- จัดการการตัดการเชื่อมต่ออัตโนมัติเมื่อ Client หลุด
"""

from fastapi import WebSocket
from app.core.logging import logger
from typing import Any, Dict, Set

class ConnectionManager:
    """
    Manages active WebSocket connections and broadcasts messages.
    Thread-safe for single-process async usage (standard FastAPI).
    """

    def __init__(self):
        self._active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self._active_connections.add(websocket)
        logger.info(
            f"[WS-Manager] Client connected — "
            f"active connections: {self.active_count}"
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a WebSocket connection."""
        self._active_connections.discard(websocket)
        logger.info(
            f"[WS-Manager] Client disconnected — "
            f"active connections: {self.active_count}"
        )

    async def broadcast(self, data: Dict[str, Any]) -> None:
        """
        Send JSON data to ALL connected clients.

        Each send is wrapped in try/except so one broken client
        does not prevent others from receiving the message.
        """
        if not self._active_connections:
            logger.debug("[WS-Manager] No active clients — broadcast skipped")
            return

        logger.info(
            f"[WS-Manager] Broadcasting to {self.active_count} client(s)"
        )

        stale: list[WebSocket] = []

        for connection in self._active_connections:
            try:
                await connection.send_json(data)
            except Exception as exc:
                logger.warning(
                    f"[WS-Manager] Failed to send to a client: {exc}"
                )
                stale.append(connection)

        # Clean up broken connections
        for connection in stale:
            self._active_connections.discard(connection)
            logger.debug("[WS-Manager] Removed stale connection after send failure")

    @property
    def active_count(self) -> int:
        """Number of currently connected clients."""
        return len(self._active_connections)


# ── Singleton ────────────────────────────────────────────────────
ws_manager = ConnectionManager()
