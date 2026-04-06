"""
Zabbix Event Normalizer
แปลง raw Zabbix webhook payload ให้เป็นรูปแบบที่อ่านง่าย
ก่อนส่งต่อไปยัง Slack notification

Zabbix Webhook Payload (typical):
{
    "event_id": "12345",
    "trigger_id": "678",
    "trigger_name": "High CPU utilization on {HOST.NAME}",
    "trigger_severity": "4",          # 0-5
    "trigger_status": "PROBLEM",      # PROBLEM / RESOLVED
    "host_name": "CSR1000v-Core",
    "host_ip": "192.168.1.1",
    "item_name": "CPU utilization",
    "item_value": "95.2",
    "event_date": "2026.03.08",
    "event_time": "14:30:00",
    "event_tags": "scope:network,device:router",
    ...
}
"""

from typing import Any, Dict, Optional
from datetime import datetime
from enum import Enum
from app.core.logging import logger


# ── Zabbix Severity Mapping ──────────────────────────────────────
class ZabbixSeverity(str, Enum):
    NOT_CLASSIFIED = "0"
    INFORMATION = "1"
    WARNING = "2"
    AVERAGE = "3"
    HIGH = "4"
    DISASTER = "5"


SEVERITY_LABEL = {
    ZabbixSeverity.NOT_CLASSIFIED: "Normal",
    ZabbixSeverity.INFORMATION: "Information",
    ZabbixSeverity.WARNING: "Warning",
    ZabbixSeverity.AVERAGE: "Average",
    ZabbixSeverity.HIGH: "High",
    ZabbixSeverity.DISASTER: "Disaster",
}

SEVERITY_EMOJI = {
    ZabbixSeverity.NOT_CLASSIFIED: "⚪",
    ZabbixSeverity.INFORMATION: "🔵",
    ZabbixSeverity.WARNING: "🟡",
    ZabbixSeverity.AVERAGE: "🟠",
    ZabbixSeverity.HIGH: "🔴",
    ZabbixSeverity.DISASTER: "🔥",
}

SEVERITY_COLOR = {
    ZabbixSeverity.NOT_CLASSIFIED: "#97AAB3",
    ZabbixSeverity.INFORMATION: "#7499FF",
    ZabbixSeverity.WARNING: "#FFC859",
    ZabbixSeverity.AVERAGE: "#FFA059",
    ZabbixSeverity.HIGH: "#E97659",
    ZabbixSeverity.DISASTER: "#E45959",
}

# ── Status mapping ───────────────────────────────────────────────
STATUS_EMOJI = {
    "PROBLEM": "🚨",
    "RESOLVED": "✅",
    "OK": "✅",
    "UPDATE": "🔄",
}


class NormalizedZabbixEvent:
    """Normalized representation of a Zabbix event."""

    def __init__(
        self,
        event_id: str,
        status: str,
        severity: ZabbixSeverity,
        host_name: str,
        host_ip: str,
        trigger_name: str,
        item_name: str,
        item_value: str,
        event_time: str,
        tags: Dict[str, str],
        description: str = "",
        trigger_url: str = "",
        interface_name: str = "",
        traffic_in: str = "",
        traffic_out: str = "",
        raw_payload: Optional[Dict[str, Any]] = None,
    ):
        self.event_id = event_id
        self.status = status.upper()
        self.severity = severity
        self.host_name = host_name
        self.host_ip = host_ip
        self.trigger_name = trigger_name
        self.item_name = item_name
        self.item_value = item_value
        self.event_time = event_time
        self.tags = tags
        self.description = description
        self.trigger_url = trigger_url
        self.interface_name = interface_name
        self.traffic_in = traffic_in
        self.traffic_out = traffic_out
        self.raw_payload = raw_payload or {}
        self.received_at = datetime.utcnow().isoformat()

    @property
    def severity_label(self) -> str:
        return SEVERITY_LABEL.get(self.severity, "Unknown")

    @property
    def severity_emoji(self) -> str:
        return SEVERITY_EMOJI.get(self.severity, "⚪")

    @property
    def severity_color(self) -> str:
        return SEVERITY_COLOR.get(self.severity, "#97AAB3")

    @property
    def status_emoji(self) -> str:
        return STATUS_EMOJI.get(self.status, "❓")

    @property
    def is_problem(self) -> bool:
        return self.status == "PROBLEM"

    @property
    def is_resolved(self) -> bool:
        return self.status in ("RESOLVED", "OK")

    @property
    def frontend_message(self) -> str:
        """Construct an easy-to-read message for frontend toasts/notifications."""
        iface = self.tags.get("interface", "").strip()
        desc = self.tags.get("description", "").strip()
        
        if iface:
            iface_display = f"{iface}({desc})" if desc else iface
            if self.item_value:
                msg = f"{self.item_value} - {iface_display}"
            else:
                msg = f"{self.trigger_name} - (Port: {iface_display})"
        elif self.item_value and ("Down" in self.item_value or "Up" in self.item_value):
            msg = self.item_value
        else:
            # Fallback for non-interface alerts (e.g., CPU, ICMP Ping, System Name)
            msg = self.trigger_name
            
        return msg.strip()

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "event_id": self.event_id,
            "status": self.status,
            "severity": self.severity.value,
            "severity_label": self.severity_label,
            "host_name": self.host_name,
            "host_ip": self.host_ip,
            "trigger_name": self.trigger_name,
            "item_name": self.item_name,
            "item_value": self.item_value,
            "interface_name": self.interface_name,
            "frontend_message": self.frontend_message,
            "event_time": self.event_time,
            "tags": self.tags,
            "description": self.description,
            "received_at": self.received_at,
        }
        # Include traffic data only when present (avoid noise)
        if self.traffic_in:
            d["traffic_in"] = self.traffic_in
        if self.traffic_out:
            d["traffic_out"] = self.traffic_out
        return d


def _humanize_value(raw: str) -> str:
    """
    Convert raw SNMP/Zabbix values to human-readable text.
    e.g. 'Down(2)' / 'Down (2)' → 'Interface Down'
    """
    if not raw:
        return raw

    # Check for pure Link status from typical strings like "Link down" or "Link up"
    low = raw.lower()
    if "link down" in low or "down" in low:
        return "Interface Down"
    if "link up" in low or "up" in low:
        return "Interface Up"

    VALUE_MAP = {
        "down(2)": "Interface Down",
        "up(1)": "Interface Up",
        "testing(3)": "Testing",
        "dormant(5)": "Dormant",
        "notpresent(6)": "Not Present",
        "lowerlayerdown(7)": "Lower Layer Down",
        "true(1)": "Enabled",
        "false(2)": "Disabled",
        "running(1)": "Running",
        "stopped(2)": "Stopped",
        "notavailable(0)": "ไม่พร้อมใช้งาน",
        "available(1)": "พร้อมใช้งาน",
        "not available(0)": "ไม่พร้อมใช้งาน",
    }

    # Normalize: strip, lowercase, remove spaces before '('
    import re
    lookup = re.sub(r"\s+\(", "(", raw.strip().lower())
    if lookup in VALUE_MAP:
        return VALUE_MAP[lookup]

    return raw


def _parse_tags(raw_tags: str) -> Dict[str, str]:
    """
    Parse Zabbix event tags string into a dict.

    Zabbix can send tags as:
      - Comma-separated: "scope:network,device:router"
      - Or as a JSON-like list
    """
    tags = {}
    if not raw_tags:
        return tags

    for pair in raw_tags.split(","):
        pair = pair.strip()
        if ":" in pair:
            key, _, value = pair.partition(":")
            tags[key.strip()] = value.strip()
        elif "=" in pair:
            key, _, value = pair.partition("=")
            tags[key.strip()] = value.strip()
        else:
            tags[pair] = ""

    return tags


def _build_event_time(payload: Dict[str, Any]) -> str:
    """Build a human-readable event timestamp from Zabbix payload fields."""
    event_date = payload.get("event_date", "")
    event_time = payload.get("event_time", "")

    if event_date and event_time:
        return f"{event_date} {event_time}"

    # Fallback: use event_timestamp (epoch)
    epoch = payload.get("event_timestamp") or payload.get("timestamp")
    if epoch:
        try:
            return datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            pass

    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _clean_zabbix_description(desc: str) -> str:
    """
    Clean up Zabbix boilerplate descriptions to get the actual meaning.
    """
    if not desc:
        return ""
    
    # Remove the standard Zabbix template boilerplate
    boilerplate = "This trigger expression works as follows:"
    if boilerplate in desc:
        # Give us whatever was written BEFORE the boilerplate, if any
        parts = desc.split(boilerplate)
        actual_desc = parts[0].strip()
        if actual_desc:
            return actual_desc
        return "" # If it was ONLY the boilerplate, just return empty
        
    return desc.strip()


def normalize_zabbix_event(payload: Dict[str, Any]) -> NormalizedZabbixEvent:
    """
    Normalize raw Zabbix webhook payload into a clean NormalizedZabbixEvent.

    Args:
        payload: Raw JSON body from Zabbix webhook action

    Returns:
        NormalizedZabbixEvent with all fields cleaned and mapped
    """
    logger.debug(f"[ZabbixNormalizer] Raw payload: {payload}")

    # ── Extract fields (Zabbix field names may vary by config) ──
    event_id = str(payload.get("event_id", payload.get("eventid", "N/A")))

    # Status: PROBLEM / RESOLVED / OK / UPDATE
    status = (
        payload.get("trigger_status")
        or payload.get("status")
        or payload.get("event_status")
        or "PROBLEM"
    ).upper()

    # Map "OK" and "0" to "RESOLVED" for consistency
    if status in ("OK", "0"):
        status = "RESOLVED"

    # Severity: 0-5
    raw_severity = str(
        payload.get("trigger_severity")
        or payload.get("severity")
        or payload.get("event_severity")
        or "0"
    )
    try:
        severity = ZabbixSeverity(raw_severity)
    except ValueError:
        severity = ZabbixSeverity.NOT_CLASSIFIED

    # Host info
    host_name = (
        payload.get("host_name")
        or payload.get("hostname")
        or payload.get("host")
        or "Unknown Host"
    )
    host_ip = (
        payload.get("host_ip")
        or payload.get("ip")
        or payload.get("hostip")
        or ""
    )

    # Trigger / problem info
    trigger_name = (
        payload.get("trigger_name")
        or payload.get("alert_subject")
        or payload.get("subject")
        or payload.get("problem")
        or "Unknown Trigger"
    )

    item_name = payload.get("item_name") or payload.get("item") or ""
    item_value = _humanize_value(
        str(payload.get("item_value") or payload.get("value") or "")
    )
    
    # If the item_value is empty, but the trigger name tells us it's a link down/up, set it
    trigger_lower = trigger_name.lower()
    if not item_value:
        if "link down" in trigger_lower or "is down" in trigger_lower:
            item_value = "Interface Down"
        elif "link up" in trigger_lower or "is up" in trigger_lower:
            item_value = "Interface Up"

    raw_description = payload.get("trigger_description") or payload.get("description") or ""
    description = _clean_zabbix_description(raw_description)
    
    trigger_url = payload.get("trigger_url") or payload.get("url") or ""

    # Interface name (dedicated field from Zabbix webhook)
    interface_name = (
        payload.get("interface_name")
        or payload.get("ifname")
        or ""
    ).strip()

    # Traffic data (SNMP values from Zabbix)
    traffic_in = str(payload.get("traffic_in") or "").strip()
    traffic_out = str(payload.get("traffic_out") or "").strip()

    # Tags
    raw_tags = payload.get("event_tags") or payload.get("tags") or ""
    if isinstance(raw_tags, dict):
        tags = raw_tags
    elif isinstance(raw_tags, list):
        tags = {}
        for t in raw_tags:
            if isinstance(t, dict):
                tags[t.get("tag", "")] = t.get("value", "")
            else:
                tags[str(t)] = ""
    else:
        tags = _parse_tags(str(raw_tags))

    # Timestamp
    event_time = _build_event_time(payload)

    normalized = NormalizedZabbixEvent(
        event_id=event_id,
        status=status,
        severity=severity,
        host_name=host_name,
        host_ip=host_ip,
        trigger_name=trigger_name,
        item_name=item_name,
        item_value=item_value,
        event_time=event_time,
        tags=tags,
        description=description,
        trigger_url=trigger_url,
        interface_name=interface_name,
        traffic_in=traffic_in,
        traffic_out=traffic_out,
        raw_payload=payload,
    )

    logger.info(
        f"[ZabbixNormalizer] Normalized event: id={normalized.event_id} "
        f"status={normalized.status} severity={normalized.severity_label} "
        f"host={normalized.host_name}"
    )

    return normalized
