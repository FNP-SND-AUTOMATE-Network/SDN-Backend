"""
Zabbix Webhook API — รับ Event จาก Zabbix แล้ว Normalize + ส่ง Slack

Endpoints:
  POST /api/v1/zabbix/webhook         — รับ event จาก Zabbix (main endpoint)
  GET  /api/v1/zabbix/events           — ดู recent events ที่ประมวลผลแล้ว
  GET  /api/v1/zabbix/stats            — ดูสถิติการรับ events

Zabbix Configuration:
  ตั้งค่า Media Type → Webhook ใน Zabbix ให้ส่ง HTTP POST มาที่:
    URL:  http://<backend-host>:8000/api/v1/zabbix/webhook
    Type: application/json

  Body Template (ตัวอย่าง):
    {
      "event_id": "{EVENT.ID}",
      "trigger_name": "{TRIGGER.NAME}",
      "trigger_severity": "{TRIGGER.SEVERITY}",
      "trigger_status": "{TRIGGER.STATUS}",
      "host_name": "{HOST.NAME}",
      "host_ip": "{HOST.IP}",
      "item_name": "{ITEM.NAME}",
      "item_value": "{ITEM.LASTVALUE}",
      "event_date": "{EVENT.DATE}",
      "event_time": "{EVENT.TIME}",
      "event_tags": "{EVENT.TAGS}",
      "trigger_description": "{TRIGGER.DESCRIPTION}",
      "trigger_url": "{TRIGGER.URL}"
    }

Authentication:
  ถ้าตั้งค่า ZABBIX_WEBHOOK_TOKEN ใน .env
  Zabbix ต้องส่ง header: Authorization: Bearer <token>
"""

from fastapi import APIRouter, HTTPException, Header, Request
from typing import Any, Dict, Optional
from app.services.zabbix_notification_service import zabbix_notification_service
from app.core.config import settings
from app.core.logging import logger

router = APIRouter(prefix="/api/v1/zabbix", tags=["Zabbix Webhook"])


# ── Auth helper ──────────────────────────────────────────────────

def _verify_token(authorization: Optional[str]):
    """Verify Bearer token if ZABBIX_WEBHOOK_TOKEN is configured."""
    expected = settings.ZABBIX_WEBHOOK_TOKEN
    if not expected:
        # No token configured = open (useful for dev)
        return

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Support both "Bearer <token>" and plain "<token>"
    token = authorization
    if token.lower().startswith("bearer "):
        token = token[7:]

    if token != expected:
        raise HTTPException(status_code=403, detail="Invalid webhook token")


# ── Endpoints ────────────────────────────────────────────────────

@router.post("/webhook")
async def receive_zabbix_event(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """
    รับ event จาก Zabbix Webhook

    Zabbix จะ POST JSON payload มาเมื่อเกิด trigger event
    Backend จะ normalize ข้อมูลให้อ่านง่าย แล้วส่งต่อไปยัง Slack

    Flow:
      Zabbix → POST /api/v1/zabbix/webhook → Normalize → Slack

    Returns:
      - status: "sent" / "failed"
      - event_id: Zabbix event ID
      - host: ชื่อ host ที่เกิด event
      - severity: ระดับความรุนแรง
      - trigger: ชื่อ trigger
    """
    # Verify token
    _verify_token(authorization)

    # Parse body
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception as e:
        logger.error(f"[ZabbixWebhook] Failed to parse JSON body: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    logger.info(f"[ZabbixWebhook] Received event from Zabbix: {payload.get('event_id', 'N/A')}")
    logger.info(
        f"[ZabbixWebhook] RAW STATUS FIELDS → "
        f"trigger_status={payload.get('trigger_status')!r}, "
        f"status={payload.get('status')!r}, "
        f"event_status={payload.get('event_status')!r}, "
        f"event_value={payload.get('event_value')!r}, "
        f"event_update_status={payload.get('event_update_status')!r}"
    )
    logger.info(f"[ZabbixWebhook] FULL PAYLOAD KEYS: {list(payload.keys())}")

    # Process: normalize → send to Slack
    result = await zabbix_notification_service.handle_zabbix_event(payload)

    return result


@router.get("/events")
async def get_zabbix_events():
    """
    ดู Zabbix events ที่ประมวลผลแล้ว (recent)

    Returns:
      - events: รายการ events ล่าสุด (max 50)
      - total: จำนวน events ทั้งหมดใน buffer
    """
    events = zabbix_notification_service.get_recent_events()
    return {
        "events": events,
        "total": len(events),
    }


@router.get("/stats")
async def get_zabbix_stats():
    """
    ดูสถิติการรับ events จาก Zabbix

    Returns:
      - total_events_processed: จำนวน events ที่ประมวลผลแล้ว
      - problems: จำนวน PROBLEM events
      - resolved: จำนวน RESOLVED events
      - failed_slack_sends: จำนวนที่ส่ง Slack ไม่สำเร็จ
      - webhook_active: Slack webhook ตั้งค่าแล้วหรือไม่
    """
    return zabbix_notification_service.get_stats()
