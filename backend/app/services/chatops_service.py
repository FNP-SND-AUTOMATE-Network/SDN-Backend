"""
ChatOps Service — Orchestrator สำหรับ Event-Driven Pipeline

รับ Event จาก Event Bus → ตรวจจับ Fault → จัดรูปแบบ Slack Message → ส่งไป Slack

ทำงานเป็น listener ของ Event Bus:
  - device.status_changed  → ตรวจจับ fault → แจ้ง Slack
  - sync.completed         → สรุปผล sync → แจ้ง Slack (ถ้ามี fault)
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from app.core.logging import logger
from app.core.event_bus import event_bus, Event
from app.clients.slack_client import SlackClient
from app.services.fault_detector import (
    FaultDetector,
    FaultEvent,
    FaultSeverity,
    FaultType,
)


# ── Emoji / icon map ────────────────────────────────────────────
SEVERITY_EMOJI = {
    FaultSeverity.CRITICAL: "🔴",
    FaultSeverity.WARNING: "🟡",
    FaultSeverity.INFO: "🔵",
    FaultSeverity.RESOLVED: "🟢",
}

FAULT_TYPE_LABEL = {
    FaultType.DEVICE_DOWN: "Device Down",
    FaultType.DEVICE_UNREACHABLE: "Device Unreachable",
    FaultType.CONNECTION_DEGRADED: "Connection Degraded",
    FaultType.DEVICE_RECOVERED: "Device Recovered",
    FaultType.DEVICE_UNMOUNTED: "Device Unmounted",
    FaultType.SYNC_COMPLETED: "Sync Completed",
    FaultType.SYNC_FAILED: "Sync Failed",
}


class ChatOpsService:
    """
    Main ChatOps orchestrator.
    Formats fault events into Slack Block Kit messages and sends them.
    """

    def __init__(self):
        self.slack = SlackClient()
        self.fault_detector = FaultDetector()
        self._register_event_handlers()

    # ── Register Event Bus handlers ──────────────────────────────
    def _register_event_handlers(self):
        event_bus.subscribe("device.status_changed", self._on_device_status_changed)
        event_bus.subscribe("sync.completed", self._on_sync_completed)
        logger.info("[ChatOps] Event handlers registered on EventBus")

    # ── Handler: device.status_changed ───────────────────────────
    async def _on_device_status_changed(self, event: Event):
        """Handle individual device status change events."""
        data = event.data

        fault = self.fault_detector.detect_from_status_change(
            node_id=data.get("node_id", "unknown"),
            device_name=data.get("device_name", ""),
            protocol=data.get("protocol", ""),
            previous_status=data.get("previous_status", ""),
            current_status=data.get("current_status", ""),
            connection_status=data.get("connection_status", ""),
        )

        if fault:
            await self._send_fault_notification(fault)

    # ── Handler: sync.completed ──────────────────────────────────
    async def _on_sync_completed(self, event: Event):
        """Handle sync completion — detect faults from results and send summary."""
        data = event.data
        sync_type = data.get("sync_type", "unknown")

        # สร้าง summary
        summary = data.get("summary", {})
        total_synced = summary.get("total_synced", 0)
        total_errors = summary.get("total_errors", 0)

        # ตรวจจับ faults จากผลลัพธ์
        faults: List[FaultEvent] = []

        # ตรวจจาก NETCONF results
        netconf = data.get("netconf", {})
        if netconf:
            faults.extend(self.fault_detector.detect_from_sync_result(netconf))

        # ตรวจจาก OpenFlow results
        openflow = data.get("openflow", {})
        if openflow:
            faults.extend(self.fault_detector.detect_from_sync_result(openflow))

        # ส่ง fault notifications
        for fault in faults:
            await self._send_fault_notification(fault)

        # ส่ง summary notification (เฉพาะเมื่อมี error หรือ fault)
        if total_errors > 0 or len(faults) > 0:
            await self._send_sync_summary(
                sync_type=sync_type,
                total_synced=total_synced,
                total_errors=total_errors,
                faults_count=len(faults),
            )

    # ── Slack message: Fault notification ────────────────────────
    async def _send_fault_notification(self, fault: FaultEvent):
        """Format and send a fault notification to Slack."""
        emoji = SEVERITY_EMOJI.get(fault.severity, "⚪")
        label = FAULT_TYPE_LABEL.get(fault.fault_type, fault.fault_type.value)

        header = f"{emoji} {fault.severity.value}: {label}"

        body_lines = [
            f"*Device:* `{fault.device_name or fault.node_id}`",
            f"*Node ID:* `{fault.node_id}`",
        ]

        if fault.protocol:
            body_lines.append(f"*Protocol:* {fault.protocol}")

        if fault.previous_status and fault.current_status:
            body_lines.append(
                f"*Status:* {fault.previous_status} → *{fault.current_status}*"
            )

        if fault.connection_status:
            body_lines.append(f"*Connection:* {fault.connection_status}")

        if fault.details:
            note = fault.details.get("note", "")
            if note:
                body_lines.append(f"*Note:* {note}")

            error = fault.details.get("error", "")
            if error:
                body_lines.append(f"*Error:* ```{str(error)[:300]}```")

        footer = f"🤖 _SDN ChatOps · {fault.timestamp}_"

        blocks = self._build_fault_blocks(header, body_lines, fault.severity, footer)

        await self.slack.send_message(text=header, blocks=blocks)

        logger.info(
            f"[ChatOps] Fault notification sent: {fault.severity.value} "
            f"- {fault.node_id} ({label})"
        )

    def _build_fault_blocks(
        self,
        header: str,
        body_lines: List[str],
        severity: FaultSeverity,
        footer: str,
    ) -> List[Dict]:
        """Build Slack Block Kit blocks for a fault notification."""
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header, "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(body_lines)},
            },
        ]

        if footer:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": footer}],
                }
            )

        return blocks

    # ── Slack message: Sync summary ──────────────────────────────
    async def _send_sync_summary(
        self,
        sync_type: str,
        total_synced: int,
        total_errors: int,
        faults_count: int,
    ):
        """Send a sync summary notification to Slack."""
        if total_errors > 0:
            emoji = "⚠️"
            status_text = "Completed with Errors"
        elif faults_count > 0:
            emoji = "🔔"
            status_text = "Completed — Faults Detected"
        else:
            emoji = "✅"
            status_text = "Completed Successfully"

        header = f"{emoji} Sync {status_text}"

        body_lines = [
            f"*Sync Type:* {sync_type}",
            f"*Devices Synced:* {total_synced}",
            f"*Errors:* {total_errors}",
            f"*Faults Detected:* {faults_count}",
        ]

        footer = f"🤖 _SDN ChatOps · Background Sync · {datetime.utcnow().isoformat()}_"

        await self.slack.send_block_message(
            header=header,
            body_lines=body_lines,
            footer=footer,
        )

    # ── Manual notification ──────────────────────────────────────
    async def send_manual_notification(
        self,
        title: str,
        message: str,
        severity: str = "INFO",
    ) -> Dict[str, Any]:
        """ส่ง notification ด้วยมือจาก API"""
        severity_emoji_map = {
            "CRITICAL": "🔴",
            "WARNING": "🟡",
            "INFO": "🔵",
            "RESOLVED": "🟢",
        }
        emoji = severity_emoji_map.get(severity.upper(), "🔵")

        success = await self.slack.send_block_message(
            header=f"{emoji} {title}",
            body_lines=[message],
            footer=f"🤖 _SDN ChatOps · Manual Notification · {datetime.utcnow().isoformat()}_",
        )

        return {
            "status": "sent" if success else "failed",
            "title": title,
            "severity": severity,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ── Test connection ──────────────────────────────────────────
    async def test_slack_connection(self) -> Dict[str, Any]:
        """Test Slack webhook connection."""
        return await self.slack.test_connection()

    # ── Status ───────────────────────────────────────────────────
    def get_status(self) -> Dict[str, Any]:
        """Get ChatOps system status."""
        return {
            "chatops_enabled": bool(self.slack.webhook_url),
            "webhook_configured": bool(self.slack.webhook_url),
            "event_bus_handlers": event_bus.registered_handlers,
            "recent_events_count": len(event_bus.recent_events),
        }


# ── Singleton ────────────────────────────────────────────────────
chatops_service = ChatOpsService()
