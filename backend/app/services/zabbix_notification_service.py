"""
Zabbix Notification Service
รับ event ที่ normalize แล้วจาก Zabbix → จัดรูปแบบ Slack Block Kit → ส่งไปยัง Slack

Flow:
  1. รับ NormalizedZabbixEvent จาก webhook handler
  2. จัดรูปแบบเป็น Slack Block Kit (rich message)
  3. ส่งผ่าน SlackClient
  4. บันทึก event ไว้ใน Event Bus สำหรับ audit
"""

from typing import Any, Dict, List
from datetime import datetime
from app.core.logging import logger
from app.core.event_bus import event_bus
from app.clients.slack_client import SlackClient
from app.core.ws_manager import ws_manager
from app.core.alert_dedup import alert_dedup
from app.normalizers.zabbix import (
    NormalizedZabbixEvent,
    ZabbixSeverity,
    normalize_zabbix_event,
)


class ZabbixNotificationService:
    """
    รับ Zabbix events ที่ normalize แล้ว
    จัดรูปแบบ Slack Block Kit message แล้วส่งออก
    """

    def __init__(self):
        self.slack = SlackClient()
        self._event_history: List[Dict[str, Any]] = []
        self._max_history = 200

    # ── Main entry point ─────────────────────────────────────────
    async def handle_zabbix_event(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Entry point: รับ raw payload จาก Zabbix API → normalize → ส่ง Slack

        Args:
            raw_payload: Raw JSON body จาก Zabbix webhook

        Returns:
            Result dict with status, event_id, etc.
        """
        # Step 1: Normalize
        event = normalize_zabbix_event(raw_payload)

        # Step 2: Build Slack blocks
        blocks = self._build_slack_blocks(event)
        fallback_text = self._build_fallback_text(event)

        # Step 3: Send to Slack
        success = await self.slack.send_message(text=fallback_text, blocks=blocks)

        # Step 3.5: Broadcast to WebSocket clients (real-time push to Frontend)
        try:
            await ws_manager.broadcast(event.to_dict())
        except Exception as ws_err:
            logger.warning(f"[ZabbixNotify] WebSocket broadcast failed (non-fatal): {ws_err}")

        # Step 3.6: Record to dedup registry (ป้องกัน Internal Fault ส่ง Slack ซ้ำ)
        alert_dedup.record_zabbix_alert(event.host_name)
        if event.host_ip:
            alert_dedup.record_zabbix_alert(event.host_ip)

        # Step 4: Emit to EventBus for audit / history
        await event_bus.emit("zabbix.event_received", event.to_dict())

        # Step 5: Track history
        record = {
            **event.to_dict(),
            "slack_sent": success,
            "processed_at": datetime.utcnow().isoformat(),
        }
        self._event_history.append(record)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

        if success:
            logger.info(
                f"[ZabbixNotify] Sent to Slack: event_id={event.event_id} "
                f"host={event.host_name} status={event.status}"
            )
        else:
            logger.error(
                f"[ZabbixNotify] Failed to send to Slack: event_id={event.event_id}"
            )

        return {
            "status": "sent" if success else "failed",
            "event_id": event.event_id,
            "host": event.host_name,
            "severity": event.severity_label,
            "trigger": event.trigger_name,
            "processed_at": record["processed_at"],
        }

    # ── Build Slack Block Kit message (clean & clear) ──────────
    def _build_slack_blocks(self, event: NormalizedZabbixEvent) -> List[Dict]:
        """
        Build clean, structured Slack Block Kit message.
        """
        # ── Extract Interface / Specific Issue from Trigger ──
        # e.g., "Huawei VRP: Interface Ethernet1/0/3(): Link down" -> "Interface Ethernet1/0/3(): Link down"
        # We try to strip the host prefix from the trigger if it exists
        clean_trigger = event.trigger_name
        if clean_trigger.startswith(f"{event.host_name}: "):
            clean_trigger = clean_trigger[len(f"{event.host_name}: "):].strip()
        elif ":" in clean_trigger:
            # Fallback for "Huawei VRP: Interface Ethernet1/0/3(): Link down"
            parts = clean_trigger.split(":", 1)
            # If the first part looks like a template prefix, keep the rest
            if "Huawei" in parts[0] or "Cisco" in parts[0] or "VRP" in parts[0]:
                clean_trigger = parts[1].strip()

        # ── Header ──
        if event.is_resolved:
            # e.g., ✅ RESOLVED: NE40ET — Interface Ethernet1/0/3(): Link up 
            # or ✅ RESOLVED: NE40ET — Interface Up
            issue_text = clean_trigger if "up" in clean_trigger.lower() or "down" in clean_trigger.lower() else event.item_value or clean_trigger
            header_text = f"✅ RESOLVED: {event.host_name} — {issue_text}"
        else:
            # e.g., 🚨 PROBLEM: NE40ET — Interface Ethernet1/0/3(): Link down
            header_text = f"{event.severity_emoji} PROBLEM: {event.host_name} — {clean_trigger}"

        if len(header_text) > 148:
            header_text = header_text[:145] + "..."

        blocks: List[Dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header_text, "emoji": True},
            },
        ]

        # ── Two-column info ──
        severity_str = event.severity_label
        if severity_str == "Not Classified":
            severity_str = "Not Classified (ระดับทั่วไป)"

        fields = [
            {"type": "mrkdwn", "text": f"*Host:*\n`{event.host_name}`"},
            {"type": "mrkdwn", "text": f"*Severity:*\n{event.severity_emoji} {severity_str}"},
            {"type": "mrkdwn", "text": f"*IP Address:*\n`{event.host_ip or 'N/A'}`"},
            {"type": "mrkdwn", "text": f"*Status:*\n{event.status_emoji} {event.status}"},
        ]
        blocks.append({"type": "section", "fields": fields})

        # ── Value / Description (concise) ──
        detail_lines = []
        if event.is_resolved:
            detail_lines.append(f"*Trigger:* {event.trigger_name}")
        if event.item_value and not event.is_resolved:
            detail_lines.append(f"*Value:* `{event.item_value}`")
            
        if event.description:
            # We already cleaned the boilerplates in normalize_zabbix_event
            # Just take the first meaningful line if there are multiple
            desc_lines = [line.strip() for line in event.description.split("\n") if line.strip()]
            if desc_lines:
                desc = desc_lines[0]
                if len(desc) > 150:
                    desc = desc[:147] + "..."
                detail_lines.append(f"*Detail:* {desc}")

        if detail_lines:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(detail_lines)},
            })

        # ── Tags ──
        if event.tags:
            tag_parts = [f"`{k}: {v}`" if v else f"`{k}`" for k, v in event.tags.items()]
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Tags:*  {' '.join(tag_parts)}"},
            })

        # ── Footer ──
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"🤖 _SDN ChatOps · Zabbix Alert_ "
                        f"· Event ID: {event.event_id} · {event.event_time}"
                    ),
                }
            ],
        })

        return blocks

    # ── Fallback plain text ──────────────────────────────────────
    def _build_fallback_text(self, event: NormalizedZabbixEvent) -> str:
        """Plain-text fallback."""
        status = "RESOLVED" if event.is_resolved else "PROBLEM"
        return (
            f"{event.severity_emoji} {status}: {event.trigger_name}\n"
            f"Host: {event.host_name} ({event.host_ip})\n"
            f"Severity: {event.severity_label} · Event ID: {event.event_id}"
        )

    # ── History / Status ─────────────────────────────────────────
    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recently processed Zabbix events."""
        return self._event_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        total = len(self._event_history)
        problems = sum(1 for e in self._event_history if e.get("status") == "PROBLEM")
        resolved = sum(1 for e in self._event_history if e.get("status") == "RESOLVED")
        failed_sends = sum(1 for e in self._event_history if not e.get("slack_sent"))

        return {
            "total_events_processed": total,
            "problems": problems,
            "resolved": resolved,
            "failed_slack_sends": failed_sends,
            "webhook_active": bool(self.slack.webhook_url),
        }


# ── Singleton ────────────────────────────────────────────────────
zabbix_notification_service = ZabbixNotificationService()
