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

        # Step 3: Send to Slack only when ChatOps is enabled and webhook is configured.
        slack_attempted = settings.CHATOPS_ENABLED and bool(self.slack.webhook_url)
        if slack_attempted:
            success = await self.slack.send_message(text=fallback_text, blocks=blocks)
        else:
            success = False
            logger.info("[ZabbixNotify] Slack send skipped (ChatOps disabled or webhook not configured)")

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
        แปล/ปรับประโยค Zabbix Trigger ให้อ่านเป็นภาษามนุษย์ (ภาษาไทย)
        เพื่อให้ผู้ดูแลระบบ(Network Admin) เข้าใจได้ทันที
        """
        t_low = trigger.lower()
        
        # 1. กลุ่ม CPU 
        if "cpu utilization" in t_low or "cpu is too high" in t_low:
            if is_resolved:
                return f"การทำงานของ CPU กลับสู่ระดับปกติ (ปัจจุบัน: {value})" if value else "การทำงานของ CPU กลับสู่ระดับปกติ"
            else:
                return f"การทำงานของ CPU สูงผิดปกติ (ตรวจพบ: {value})" if value else "การทำงานของ CPU สูงผิดปกติ"
                
        # 2. กลุ่ม Memory
        if "memory utilization" in t_low or "lack of free memory" in t_low:
            if is_resolved:
                return f"หน่วยความจำ (Memory) กลับสู่ระดับปกติ (ปัจจุบัน: {value})" if value else "หน่วยความจำ (Memory) กลับสู่ระดับปกติ"
            else:
                return f"หน่วยความจำ (Memory) ถูกใช้งานสูงผิดปกติ (ตรวจพบ: {value})" if value else "หน่วยความจำ (Memory) ถูกใช้งานสูงผิดปกติ"

        # 3. กลุ่ม Ping / Network Status / ICMP
        if "ping loss" in t_low:
            if is_resolved:
                return f"สถานะ Ping กลับสู่ปกติ (Loss: {value})" if value else "สถานะ Ping กลับสู่ปกติ"
            else:
                return f"พบการสูญหายของแพ็กเกจ Ping สูง (Loss: {value})" if value else "พบการสูญหายของแพ็กเกจ Ping สูง"
                
        if "ping response time" in t_low:
            if is_resolved:
                return f"เวลาตอบสนองของ Ping กลับสู่ปกติ (เวลา: {value})" if value else "เวลาตอบสนองของ Ping กลับสู่ปกติ"
            else:
                return f"เวลาตอบสนองของ Ping สูงเกินไป (เวลา: {value})" if value else "เวลาตอบสนองของ Ping สูงเกินไป"
                
        if "unavailable by icmp" in t_low:
            if is_resolved:
                return f"อุปกรณ์สามารถเชื่อมต่อผ่านระยะไกล (ICMP) ได้ปกติ"
            else:
                return f"อุปกรณ์ไม่สามารถเชื่อมต่อผ่านการ Ping (ICMP) ได้ (Down)"

        # 4. กลุ่ม Reboot / Uptime
        if "restarted" in t_low or "has been restarted" in t_low:
            if is_resolved:
                return f"อุปกรณ์สถานะปกติหลังจากการเริ่มระบบ (Uptime: {value})" if value else "อุปกรณ์สถานะปกติหลังจากการเริ่มระบบ"
            else:
                return f"อุปกรณ์เพิ่งถูกเริ่มระบบใหม่ (Uptime: {value})" if value else "อุปกรณ์เพิ่งถูกเริ่มระบบใหม่ (Restarted)"

        # 5. กลุ่ม Interface/Port/Link
        if "link down" in t_low or "is down" in t_low:
            return f"พอร์ต/รอยต่อหยุดทำงาน ({trigger})"
            
        if "link up" in t_low or "is up" in t_low:
            return f"พอร์ต/รอยต่อกลับมาทำงานปกติ ({trigger})"

        # 6. กลุ่ม Temperature
        if "temperature is above" in t_low or "high temperature" in t_low:
            if is_resolved:
                return f"อุณหภูมิของอุปกรณ์ลดลงสู่ระดับปกติ (ปัจจุบัน: {value})" if value else "อุณหภูมิของอุปกรณ์ลดลงสู่ระดับปกติ"
            else:
                return f"อุณหภูมิของอุปกรณ์สูงผิดปกติ (ตรวจพบ: {value})" if value else "อุณหภูมิของอุปกรณ์สูงผิดปกติ"

        # 7. กลุ่ม Power Supply / Fan / Hardware
        if "power supply" in t_low:
            return f"ระบบการจ่ายไฟ (Power Supply) กลับมาทำงานปกติ" if is_resolved else f"พบความผิดปกติของระบบการจ่ายไฟ (Power Supply)!"
        if "fan is" in t_low or "fan failure" in t_low:
            return f"พัดลมระบายความร้อนกลับมาทำงานปกติ" if is_resolved else f"พบความผิดปกติของพัดลมระบายความร้อน (Fan)!"
            
        # 8. กลุ่ม BGP/OSPF/Routing
        if "bgp session" in t_low or "ospf neighbor" in t_low:
            proto = "BGP" if "bgp" in t_low else "OSPF"
            return f"การเชื่อมต่อเส้นทาง {proto} กลับสู่สถานะปกติ" if is_resolved else f"สายสำรอง/เส้นทาง {proto} ขัดข้อง (Down)!"

        # กรณีอื่น ๆ (Fallback)
        if is_resolved:
            return f"แจ้งเตือนเข้าสู่สภาวะปกติ: {trigger} (ค่าล่าสุด: {value})" if value else f"แจ้งเตือนเข้าสู่สภาวะปกติ: {trigger}"
        else:
            return f"แจ้งเตือนปัญหา: {trigger} (ปัจจุบัน: {value})" if value else f"แจ้งเตือนปัญหา: {trigger}"

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
                
        # Remove annoying (Configured_via_ODL) wrapper if present
        clean_trigger = clean_trigger.replace("(Configured_via_ODL)", "")

        # ── Header ──
        humanized_issue = self._humanize_alert_text(clean_trigger, event.item_value, event.is_resolved)
        
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

        # ── Two-column info ──
        severity_str = event.severity_label

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
            "chatops_enabled": settings.CHATOPS_ENABLED,
            "failed_slack_sends": failed_sends,
            "webhook_active": bool(self.slack.webhook_url),
        }


# ── Singleton ────────────────────────────────────────────────────
zabbix_notification_service = ZabbixNotificationService()
