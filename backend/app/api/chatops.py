"""
ChatOps API — REST endpoints สำหรับ ChatOps Network Fault Management

Endpoints:
  GET  /api/v1/chatops/status    — ดูสถานะระบบ ChatOps
  POST /api/v1/chatops/test      — ทดสอบ Slack connection
  POST /api/v1/chatops/notify    — ส่ง notification ด้วยมือ
  GET  /api/v1/chatops/events    — ดู recent events จาก Event Bus
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.services.chatops_service import chatops_service
from app.core.event_bus import event_bus
from app.core.config import settings

router = APIRouter(prefix="/api/v1/chatops", tags=["ChatOps"])


# ── Request / Response Models ────────────────────────────────────

class ManualNotifyRequest(BaseModel):
    title: str
    message: str
    severity: Optional[str] = "INFO"  # CRITICAL, WARNING, INFO, RESOLVED


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/status")
async def chatops_status():
    """
    ดูสถานะระบบ ChatOps

    Returns:
        - chatops_enabled: ระบบเปิดใช้งานหรือไม่
        - webhook_configured: Webhook URL ตั้งค่าแล้วหรือไม่
        - event_bus_handlers: รายการ handlers ที่ register ไว้
        - recent_events_count: จำนวน events ล่าสุด
    """
    status = chatops_service.get_status()
    status["chatops_config_enabled"] = settings.CHATOPS_ENABLED
    return status


@router.post("/test")
async def test_slack_connection():
    """
    ทดสอบการเชื่อมต่อ Slack Webhook

    ส่ง test message ไปยัง Slack channel ที่ตั้งค่าไว้
    เพื่อยืนยันว่า webhook ทำงานได้ปกติ
    """
    if not settings.CHATOPS_ENABLED:
        raise HTTPException(status_code=400, detail="ChatOps is disabled (CHATOPS_ENABLED=false)")

    result = await chatops_service.test_slack_connection()
    return result


@router.post("/notify")
async def send_manual_notification(req: ManualNotifyRequest):
    """
    ส่ง notification ไปยัง Slack ด้วยมือ

    Body:
        - title: หัวข้อข้อความ
        - message: เนื้อหาข้อความ
        - severity: ระดับความรุนแรง (CRITICAL, WARNING, INFO, RESOLVED)
    """
    if not settings.CHATOPS_ENABLED:
        raise HTTPException(status_code=400, detail="ChatOps is disabled (CHATOPS_ENABLED=false)")

    if req.severity and req.severity.upper() not in ("CRITICAL", "WARNING", "INFO", "RESOLVED"):
        raise HTTPException(status_code=422, detail="severity must be one of: CRITICAL, WARNING, INFO, RESOLVED")

    result = await chatops_service.send_manual_notification(
        title=req.title,
        message=req.message,
        severity=req.severity or "INFO",
    )
    return result


@router.get("/events")
async def get_recent_events():
    """
    ดู recent events จาก Event Bus (สำหรับ debug)

    Returns:
        - events: รายการ events ล่าสุด (max 50)
        - total: จำนวน events ทั้งหมดใน buffer
    """
    events = event_bus.recent_events
    return {
        "events": events,
        "total": len(events),
    }
