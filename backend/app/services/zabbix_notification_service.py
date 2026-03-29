"""
Zabbix Notification Service
รับ event ที่ normalize แล้วจาก Zabbix → จัดรูปแบบ Slack Block Kit → ส่งไปยัง Slack

Flow:
  1. รับ NormalizedZabbixEvent จาก webhook handler
  2. จัดรูปแบบเป็น Slack Block Kit (rich message)
  3. ส่งผ่าน SlackClient
  4. บันทึก event ไว้ใน Event Bus สำหรับ audit
"""

import re
from typing import Any, Dict, List
from datetime import datetime
from app.core.logging import logger
from app.core.event_bus import event_bus
from app.clients.slack_client import SlackClient
from app.core.config import settings
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

    async def handle_zabbix_event(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Entry point: รับ raw payload จาก Zabbix API → normalize → ส่ง Slack

        Args:
            raw_payload: Raw JSON body จาก Zabbix webhook

        Returns:
            Result dict with status, event_id, etc.
        """
        event = normalize_zabbix_event(raw_payload)

        blocks = self._build_slack_blocks(event)
        fallback_text = self._build_fallback_text(event)

        slack_attempted = settings.CHATOPS_ENABLED and bool(self.slack.webhook_url)
        if slack_attempted:
            success = await self.slack.send_message(text=fallback_text, blocks=blocks)
        else:
            success = False
            logger.info("[ZabbixNotify] Slack send skipped (ChatOps disabled or webhook not configured)")

        try:
            await ws_manager.broadcast(event.to_dict())
        except Exception as ws_err:
            logger.warning(f"[ZabbixNotify] WebSocket broadcast failed (non-fatal): {ws_err}")

        alert_dedup.record_zabbix_alert(event.host_name)
        if event.host_ip:
            alert_dedup.record_zabbix_alert(event.host_ip)

        await event_bus.emit("zabbix.event_received", event.to_dict())

        record = {
            **event.to_dict(),
            "slack_attempted": slack_attempted,
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
        elif slack_attempted:
            logger.error(
                f"[ZabbixNotify] Failed to send to Slack: event_id={event.event_id}"
            )

        if slack_attempted and success:
            status = "sent"
        elif slack_attempted:
            status = "failed"
        else:
            status = "accepted"

        return {
            "status": status,
            "event_id": event.event_id,
            "host": event.host_name,
            "severity": event.severity_label,
            "trigger": event.trigger_name,
            "processed_at": record["processed_at"],
        }

    def _humanize_alert_text(self, trigger: str, value: str, is_resolved: bool) -> str:
        """
        Convert Zabbix trigger text into clear human-readable English.
        """
        t_low = trigger.lower()
        
        if "cpu utilization" in t_low or "cpu is too high" in t_low:
            if is_resolved:
                return f"CPU usage returned to normal (current: {value})" if value else "CPU usage returned to normal"
            else:
                return f"High CPU usage detected (value: {value})" if value else "High CPU usage detected"
                
        if "memory utilization" in t_low or "lack of free memory" in t_low:
            if is_resolved:
                return f"Memory usage returned to normal (current: {value})" if value else "Memory usage returned to normal"
            else:
                return f"High memory usage detected (value: {value})" if value else "High memory usage detected"

        if "ping loss" in t_low:
            if is_resolved:
                return f"Ping status returned to normal (loss: {value})" if value else "Ping status returned to normal"
            else:
                return f"High ping packet loss detected (loss: {value})" if value else "High ping packet loss detected"
                
        if "ping response time" in t_low:
            if is_resolved:
                return f"Ping response time returned to normal (time: {value})" if value else "Ping response time returned to normal"
            else:
                return f"High ping response time detected (time: {value})" if value else "High ping response time detected"
                
        if "unavailable by icmp" in t_low:
            if is_resolved:
                return f"Device is reachable via ICMP"
            else:
                return f"Device is unreachable via ICMP (down)"

        if "restarted" in t_low or "has been restarted" in t_low:
            if is_resolved:
                return f"Device is stable after reboot (uptime: {value})" if value else "Device is stable after reboot"
            else:
                return f"Device has recently restarted (uptime: {value})" if value else "Device has recently restarted"

        if "link down" in t_low or "is down" in t_low:
            if is_resolved:
                return f"Port/interface is back up ({trigger})"
            return f"Port/interface is down ({trigger})"
            
        if "link up" in t_low or "is up" in t_low:
            return f"Port/interface is back up ({trigger})"

        if "temperature is above" in t_low or "high temperature" in t_low:
            if is_resolved:
                return f"Device temperature returned to normal (current: {value})" if value else "Device temperature returned to normal"
            else:
                return f"High device temperature detected (value: {value})" if value else "High device temperature detected"

        if "power supply" in t_low:
            return "Power supply status returned to normal" if is_resolved else "Power supply issue detected"
        if "fan is" in t_low or "fan failure" in t_low:
            return "Cooling fan status returned to normal" if is_resolved else "Cooling fan issue detected"
            
        if "bgp session" in t_low or "ospf neighbor" in t_low:
            proto = "BGP" if "bgp" in t_low else "OSPF"
            return f"{proto} adjacency returned to normal" if is_resolved else f"{proto} adjacency is down"

        if is_resolved:
            return f"Alert resolved: {trigger} (latest value: {value})" if value else f"Alert resolved: {trigger}"
        else:
            return f"Problem detected: {trigger} (current value: {value})" if value else f"Problem detected: {trigger}"

    def _trigger_text_for_status(self, trigger: str, is_resolved: bool) -> str:
        """Adjust trigger text to match the current event status."""
        if not trigger:
            return trigger
        if not is_resolved:
            return trigger

        replacements = [
            (r"\blink down\b", "Link up"),
            (r"\binterface down\b", "Interface up"),
            (r"\bis down\b", "is up"),
            (r"\bunavailable by icmp\b", "Reachable by ICMP"),
            (r"\bnot reachable\b", "Reachable"),
            (r"\bhigh cpu utilization\b", "CPU utilization back to normal"),
            (r"\bcpu is too high\b", "CPU utilization back to normal"),
            (r"\black of free memory\b", "Memory level back to normal"),
            (r"\bmemory utilization\b", "Memory utilization back to normal"),
            (r"\bhigh temperature\b", "Temperature back to normal"),
            (r"\btemperature is above\b", "Temperature back to normal"),
            (r"\bfan failure\b", "Fan recovered"),
            (r"\bpower supply\b", "Power supply normal"),
        ]

        transformed = trigger
        for pattern, replacement in replacements:
            transformed = re.sub(pattern, replacement, transformed, flags=re.IGNORECASE)

        return transformed

    def _value_text_for_status(self, value: str, is_resolved: bool) -> str:
        """Adjust value text to match resolved semantics (e.g., Down -> Up)."""
        if not value:
            return value
        if not is_resolved:
            return value

        replacements = [
            (r"\binterface down\b", "Interface Up"),
            (r"\blink down\b", "Link Up"),
            (r"\bdown\b", "Up"),
            (r"\bunavailable\b", "Available"),
            (r"\bhigh\b", "Normal"),
        ]

        transformed = value
        for pattern, replacement in replacements:
            transformed = re.sub(pattern, replacement, transformed, flags=re.IGNORECASE)
        return transformed

    def _build_slack_blocks(self, event: NormalizedZabbixEvent) -> List[Dict]:
        """
        Build clean, structured Slack Block Kit message.
        """
        clean_trigger = event.trigger_name
        if clean_trigger.startswith(f"{event.host_name}: "):
            clean_trigger = clean_trigger[len(f"{event.host_name}: "):].strip()
        elif ":" in clean_trigger:
            parts = clean_trigger.split(":", 1)
            if "Huawei" in parts[0] or "Cisco" in parts[0] or "VRP" in parts[0]:
                clean_trigger = parts[1].strip()

        clean_trigger = clean_trigger.replace("(Configured_via_ODL)", "")

        display_trigger = self._trigger_text_for_status(clean_trigger, event.is_resolved)
        display_value = self._value_text_for_status(event.item_value, event.is_resolved)
        humanized_issue = self._humanize_alert_text(display_trigger, display_value, event.is_resolved)
        
        if event.is_resolved:
            header_text = f"✅ RESOLVED: {event.host_name} — {humanized_issue}"
        else:
            header_text = f"{event.severity_emoji} PROBLEM: {event.host_name} — {humanized_issue}"

        if len(header_text) > 148:
            header_text = header_text[:145] + "..."

        blocks: List[Dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header_text, "emoji": True},
            },
        ]

        severity_str = event.severity_label

        fields = [
            {"type": "mrkdwn", "text": f"*Host:*\n`{event.host_name}`"},
            {"type": "mrkdwn", "text": f"*Severity:*\n{event.severity_emoji} {severity_str}"},
            {"type": "mrkdwn", "text": f"*IP Address:*\n`{event.host_ip or 'N/A'}`"},
            {"type": "mrkdwn", "text": f"*Status:*\n{event.status_emoji} {event.status}"},
        ]
        blocks.append({"type": "section", "fields": fields})

        detail_lines = []
        if event.is_resolved:
            detail_lines.append(f"*Trigger:* {display_trigger}")
        if display_value and not event.is_resolved:
            detail_lines.append(f"*Value:* `{display_value}`")
        if display_value and event.is_resolved:
            detail_lines.append(f"*Current:* `{display_value}`")
            
        if event.description:
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

        if event.tags:
            tag_parts = [f"`{k}: {v}`" if v else f"`{k}`" for k, v in event.tags.items()]
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Tags:*  {' '.join(tag_parts)}"},
            })

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

    def _build_fallback_text(self, event: NormalizedZabbixEvent) -> str:
        """Plain-text fallback."""
        status = "RESOLVED" if event.is_resolved else "PROBLEM"
        trigger_text = self._trigger_text_for_status(event.trigger_name, event.is_resolved)
        value_text = self._value_text_for_status(event.item_value, event.is_resolved)
        issue_text = self._humanize_alert_text(trigger_text, value_text, event.is_resolved)
        return (
            f"{event.severity_emoji} {status}: {event.host_name} - {issue_text}\n"
            f"Trigger: {trigger_text}\n"
            f"Host: {event.host_name} ({event.host_ip})\n"
            f"Severity: {event.severity_label} · Event ID: {event.event_id}"
        )

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
            "chatops_enabled": settings.CHATOPS_ENABLED,
            "failed_slack_sends": failed_sends,
            "webhook_active": bool(self.slack.webhook_url),
        }

zabbix_notification_service = ZabbixNotificationService()
