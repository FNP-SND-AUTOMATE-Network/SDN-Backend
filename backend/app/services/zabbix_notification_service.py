"""
Zabbix Notification Service
บริการรับ Event จาก Zabbix Webhook และส่งแจ้งเตือนไปยัง Slack

หน้าที่หลัก:
- รับ NormalizedZabbixEvent จาก Webhook Handler
- จัดรูปแบบเป็น Slack Block Kit (ข้อความสวย)
- ส่งผ่าน SlackClient
- บันทึก Event ลง Database และ Event Bus (สำหรับ Audit)
- Broadcast แจ้งเตือนผ่าน WebSocket ไปยัง Frontend

Flow:
  Zabbix Webhook → Normalize → จัดรูปแบบ Block Kit → ส่ง Slack + WebSocket + DB
"""

import re
from typing import Any, Dict, List, Optional
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
from app.database import get_prisma_client
from app.services.phpipam_service import PhpipamService


class ZabbixNotificationService:
    """
    รับ Zabbix events ที่ normalize แล้ว
    จัดรูปแบบ Slack Block Kit message แล้วส่งออก
    """

    # Regex: "Interface TEN GI 4/0(): Link down" → "TEN GI 4/0"
    _RE_IFACE_NAME = re.compile(
        r'Interface\s+([\w\s\/\-\.]+?)(?:\([^)]*\))?\s*:', re.IGNORECASE,
    )
    # Fallback: "Link down on TEN GI 4/0"
    _RE_IFACE_FALLBACK = re.compile(
        r'(?:Link down|Link up|is down|is up)\s+(?:on\s+)?([\w\s\/\-\.]+)', re.IGNORECASE,
    )
    # Fallback 2: "TEN GI 4/0 is down"
    _RE_IFACE_FALLBACK2 = re.compile(
        r'^([\w\s\/\-\.]+?)\s+is\s+(?:down|up)', re.IGNORECASE,
    )

    # Cisco / Huawei prefix broad mapping
    # Maps fuzzy/short prefixes to exact ODL standard names regardless of spaces/casing
    _IFACE_PREFIX_MAP = {
        # 100G
        "hu": "HundredGigE", "hundredgige": "HundredGigE", "hundredgigabitethernet": "HundredGigE",
        # 40G
        "fo": "FortyGigabitEthernet", "fortygige": "FortyGigabitEthernet", "fortygigabitethernet": "FortyGigabitEthernet",
        # 25G
        "tw": "TwentyFiveGigE", "twentyfivegige": "TwentyFiveGigE",
        # 10G
        "te": "TenGigabitEthernet", "tengi": "TenGigabitEthernet", 
        "tengigabit": "TenGigabitEthernet", "tengigabitethernet": "TenGigabitEthernet",
        "tengige": "TenGigabitEthernet", "xge": "10GE", "10ge": "10GE",
        # 1G
        "gi": "GigabitEthernet", "ge": "GigabitEthernet", "gig": "GigabitEthernet",
        "gigabit": "GigabitEthernet", "gigabitethernet": "GigabitEthernet",
        # 100M
        "fa": "FastEthernet", "fast": "FastEthernet", "fastethernet": "FastEthernet",
        # Ethernet / Mgmt
        "eth": "Ethernet", "ethernet": "Ethernet",
        "meth": "MEth", "mgmt": "MgmtEth", "mgmteth": "MgmtEth",
        # Logical
        "lo": "Loopback", "loopback": "Loopback",
        "vl": "Vlan", "vlan": "Vlan", "vlanif": "Vlanif",
        "tu": "Tunnel", "tunnel": "Tunnel",
        "se": "Serial", "serial": "Serial",
        "po": "Port-channel", "portchannel": "Port-channel",
    }

    def __init__(self):
        self.slack = SlackClient()
        self.phpipam_service = PhpipamService()
        self._event_history: List[Dict[str, Any]] = []
        self._max_history = 200
        self._db_updates = 0

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

        # 5. Real-time DB update (Interface/Device status from Zabbix event)
        await self._update_db_from_event(event)

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

        # Traffic info (if available from Zabbix SNMP)
        if event.traffic_in or event.traffic_out:
            traffic_parts = []
            if event.traffic_in:
                traffic_parts.append(f"*Traffic In:* `{event.traffic_in}`")
            if event.traffic_out:
                traffic_parts.append(f"*Traffic Out:* `{event.traffic_out}`")
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "  |  ".join(traffic_parts)},
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

    # ────────────────────────────────────────────────────────────────
    # Real-time DB Update from Zabbix Events
    # ────────────────────────────────────────────────────────────────

    async def _update_db_from_event(self, event: NormalizedZabbixEvent) -> None:
        """
        Real-time DB update from Zabbix event.

        Non-blocking, fail-safe — errors logged but never break notification flow.
        ODL sync remains ground truth; Zabbix events provide fast interim updates.

        Handles:
        - Interface link down/up → Interface.status = UP/DOWN
        - ICMP unreachable      → DeviceNetwork.status = OFFLINE/ONLINE
        """
        try:
            prisma = get_prisma_client()
            trigger_lower = event.trigger_name.lower()

            # 1. Find matching device in DB
            device = await self._find_device_by_event(prisma, event)
            if not device:
                logger.debug(
                    f"[ZabbixDB] No matching device for host='{event.host_name}' "
                    f"ip='{event.host_ip}' — skipping DB update"
                )
                return

            updated = False

            # 2a. Interface link events
            is_iface_event = any(
                kw in trigger_lower
                for kw in ("link down", "link up", "is down", "is up", "operational status")
            )
            if is_iface_event:
                updated = await self._handle_interface_event(prisma, device, event)

            # 2b. Device-level ICMP reachability events
            is_icmp_event = any(
                kw in trigger_lower
                for kw in ("unavailable by icmp", "unreachable", "not reachable")
            )
            if is_icmp_event:
                updated = await self._handle_reachability_event(prisma, device, event) or updated

            # 2c. Device reboot events (just log — ODL handles actual status)
            if "has been restarted" in trigger_lower or "restarted" in trigger_lower:
                if event.is_problem:
                    logger.info(
                        f"[ZabbixDB] Device {device.device_name} has been restarted "
                        f"(event_id={event.event_id}). ODL will re-sync connection status."
                    )

            if updated:
                self._db_updates += 1
                logger.info(
                    f"[ZabbixDB] ✓ Real-time update applied: device={device.device_name} "
                    f"event_id={event.event_id}"
                )

        except Exception as e:
            # Never let DB failures break the Slack/WebSocket notification pipeline
            logger.warning(f"[ZabbixDB] DB update failed (non-fatal): {e}")

    async def _find_device_by_event(self, prisma, event: NormalizedZabbixEvent):
        """
        Match Zabbix host → DB device using multiple fallback strategies:
          1. host_name → device_name
          2. host_name → node_id
          3. host_ip   → ip_address
          4. host_ip   → netconf_host
        """
        hn = event.host_name.strip()
        ip = event.host_ip.strip()

        if hn:
            device = await prisma.devicenetwork.find_first(where={"device_name": hn})
            if device:
                return device
            device = await prisma.devicenetwork.find_first(where={"node_id": hn})
            if device:
                return device

        if ip:
            device = await prisma.devicenetwork.find_first(where={"ip_address": ip})
            if device:
                return device
            device = await prisma.devicenetwork.find_first(where={"netconf_host": ip})
            if device:
                return device

        return None

    def _extract_interface_name(self, event: NormalizedZabbixEvent) -> Optional[str]:
        """
        Extract physical interface name from Zabbix event.

        Priority:
          1. Zabbix tag "interface" (most reliable, e.g. "Gi4")
          2. Zabbix webhook field "interface_name" (dedicated param)
          3. Regex from trigger_name (e.g. "Interface Ethernet1/0/2(): Link down")

        Sub-interfaces (e.g. Ethernet1/0/2.4094) are filtered out.
        """
        # Priority 1: Zabbix tags (most reliable source)
        iface_from_tag = event.tags.get("interface", "").strip()
        if iface_from_tag:
            # Tags might contain sub-interfaces too — filter them
            if "." in iface_from_tag:
                parts = iface_from_tag.rsplit(".", 1)
                if parts[-1].isdigit():
                    logger.debug(f"[ZabbixDB] Skipping sub-interface from tag: {iface_from_tag}")
                    return None
            return iface_from_tag

        # Priority 2: Dedicated interface_name field from Zabbix webhook
        if event.interface_name:
            iface = event.interface_name
            if "." in iface:
                parts = iface.rsplit(".", 1)
                if parts[-1].isdigit():
                    logger.debug(f"[ZabbixDB] Skipping sub-interface from interface_name: {iface}")
                    return None
            return iface

        # Priority 3: Regex extraction from trigger_name
        for pattern in (self._RE_IFACE_NAME, self._RE_IFACE_FALLBACK, self._RE_IFACE_FALLBACK2):
            match = pattern.search(event.trigger_name)
            if match:
                iface = match.group(1).strip()
                if "." in iface:
                    parts = iface.rsplit(".", 1)
                    if parts[-1].isdigit():
                        logger.debug(f"[ZabbixDB] Skipping sub-interface: {iface}")
                        return None
                return iface
        return None

    def _expand_interface_name(self, raw_name: str) -> List[str]:
        """
        Broadly parses and expands interface names, forgiving whitespace and formatting.
        Handles: "TEN GI 4/0" → ["TEN GI 4/0", "TenGigabitEthernet4/0"]
                 "Gi0/0/1"    → ["Gi0/0/1", "GigabitEthernet0/0/1"]
                 "10GE 1"     → ["10GE 1", "10GE1"]
        """
        # Remove spaces and convert to lowercase for easy matching
        clean_name = re.sub(r'\s+', '', raw_name).lower()
        candidates = [raw_name.strip()]

        # Find longest matching prefix
        matched_prefix = None
        for p in sorted(self._IFACE_PREFIX_MAP.keys(), key=len, reverse=True):
            if clean_name.startswith(p):
                matched_prefix = p
                break
                
        if matched_prefix:
            std_name = self._IFACE_PREFIX_MAP[matched_prefix]
            suffix_clean = clean_name[len(matched_prefix):]
            if suffix_clean:
                candidates.append(f"{std_name}{suffix_clean}")
                
        return list(dict.fromkeys(candidates))

    async def _find_interface_in_db(self, prisma, device_id: str, iface_name: str):
        """
        Find interface in DB trying multiple name variants.

        Lookup order (stops at first match):
          1. Exact match: "Gi4"
          2. Expanded name: "GigabitEthernet4"
          3. Contains (startswith): name starts with expanded prefix
        """
        candidates = self._expand_interface_name(iface_name)

        for name in candidates:
            interface = await prisma.interface.find_first(
                where={"device_id": device_id, "name": name}
            )
            if interface:
                return interface

        # Last resort: startswith match (handles "GigabitEthernet4" vs "GigabitEthernet4/0")
        for name in candidates:
            interface = await prisma.interface.find_first(
                where={
                    "device_id": device_id,
                    "name": {"startswith": name},
                }
            )
            if interface:
                return interface

        return None

    async def _handle_interface_event(
        self, prisma, device, event: NormalizedZabbixEvent
    ) -> bool:
        """
        Update Interface.status based on link up/down event.
        Returns True if a DB row was actually changed.

        Uses tag-based interface name (primary) with short→full expansion
        to match Zabbix abbreviated names (Gi4) to ODL full names (GigabitEthernet4).
        """
        iface_name = self._extract_interface_name(event)
        if not iface_name:
            logger.debug(
                f"[ZabbixDB] Could not extract interface from: "
                f"'{event.trigger_name[:80]}'"
            )
            return False

        # RESOLVED = problem cleared → port is back UP
        new_status = "UP" if event.is_resolved else "DOWN"

        # Look up interface with multi-strategy name matching
        interface = await self._find_interface_in_db(prisma, device.id, iface_name)
        if not interface:
            candidates = self._expand_interface_name(iface_name)
            logger.debug(
                f"[ZabbixDB] Interface not found for {device.device_name}. "
                f"Tried: {candidates}"
            )
            return False

        old_status = interface.status
        changed = False

        if old_status != new_status:
            await prisma.interface.update(
                where={"id": interface.id},
                data={"status": new_status},
            )
            logger.info(
                f"[ZabbixDB] Interface {device.device_name}/{interface.name}: "
                f"{old_status} → {new_status} (zabbix name: {iface_name})"
            )
            changed = True

        return changed

    async def _handle_reachability_event(
        self, prisma, device, event: NormalizedZabbixEvent
    ) -> bool:
        """
        Update DeviceNetwork.status based on ICMP reachability event.
        Returns True if a DB row was actually changed.
        """
        new_status = "ONLINE" if event.is_resolved else "OFFLINE"

        old_status = device.status
        changed = False
        
        if old_status != new_status:
            await prisma.devicenetwork.update(
                where={"id": device.id},
                data={"status": new_status},
            )
            # Sync phpIPAM tag to match new device status
            await self.phpipam_service.sync_device_status_to_ipam(device.id, new_status)
            logger.info(
                f"[ZabbixDB] Device reachability {device.device_name}: "
                f"{old_status} → {new_status}"
            )
            changed = True

        return changed

    # ────────────────────────────────────────────────────────────────
    # History & Stats
    # ────────────────────────────────────────────────────────────────

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
            "db_updates": self._db_updates,
            "webhook_active": bool(self.slack.webhook_url),
        }

zabbix_notification_service = ZabbixNotificationService()
