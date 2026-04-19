"""
Fault Detector Service
ตรวจจับสถานการณ์ผิดปกติ (Fault) จากการเปลี่ยนสถานะของอุปกรณ์

หน้าที่หลัก:
- วิเคราะห์การเปลี่ยน Status (Transition) แล้วสร้าง FaultEvent
- กำหนดระดับความรุนแรง: CRITICAL, WARNING, INFO, RESOLVED
- ใช้ร่วมกับ ChatOpsService ในการส่งแจ้งเตือนไป Slack

ระดับความรุนแรง (Severity):
  CRITICAL  — อุปกรณ์ Offline / เข้าถึงไม่ได้ (เดิมออนไลน์อยู่)
  WARNING   — การเชื่อมต่อไม่เสถียร (connecting)
  INFO      — การเปลี่ยนสถานะทั่วไป
  RESOLVED  — อุปกรณ์กลับมาออนไลน์แล้ว
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from enum import Enum
from app.core.logging import logger


class FaultSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"
    RESOLVED = "RESOLVED"


class FaultType(str, Enum):
    DEVICE_DOWN = "device_down"
    DEVICE_UNREACHABLE = "device_unreachable"
    CONNECTION_DEGRADED = "connection_degraded"
    DEVICE_RECOVERED = "device_recovered"
    DEVICE_UNMOUNTED = "device_unmounted"
    SYNC_COMPLETED = "sync_completed"
    SYNC_FAILED = "sync_failed"


class FaultEvent:
    """แทนข้อมูลของ Fault ที่ตรวจพบ พร้อมรายละเอียดทั้งหมด (ประเภท, ระดับความรุนแรง, อุปกรณ์, status)"""

    def __init__(
        self,
        fault_type: FaultType,
        severity: FaultSeverity,
        node_id: str,
        device_name: str = "",
        protocol: str = "",
        previous_status: str = "",
        current_status: str = "",
        connection_status: str = "",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.fault_type = fault_type
        self.severity = severity
        self.node_id = node_id
        self.device_name = device_name or node_id
        self.protocol = protocol
        self.previous_status = previous_status
        self.current_status = current_status
        self.connection_status = connection_status
        self.details = details or {}
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """แปลง FaultEvent เป็น Dictionary สำหรับส่งผ่าน API หรือ Event Bus"""
        return {
            "fault_type": self.fault_type.value,
            "severity": self.severity.value,
            "node_id": self.node_id,
            "device_name": self.device_name,
            "protocol": self.protocol,
            "previous_status": self.previous_status,
            "current_status": self.current_status,
            "connection_status": self.connection_status,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class FaultDetector:
    """
    วิเคราะห์การเปลี่ยน Status ของอุปกรณ์และสร้าง FaultEvent
    - ตรวจสอบ Status Transition ว่าเข้าเงื่อนไข (CRITICAL/WARNING/RESOLVED)
    - วิเคราะห์ผล Sync เพื่อหาอุปกรณ์ที่ Down หลัง Sync
    """

    # status transitions ที่ถือว่าเป็น fault
    CRITICAL_TRANSITIONS = {
        ("ONLINE", "OFFLINE"),
        ("ONLINE", "MAINTENANCE"),
    }

    WARNING_TRANSITIONS = {
        ("ONLINE", "OTHER"),
    }

    RESOLVED_TRANSITIONS = {
        ("OFFLINE", "ONLINE"),
        ("MAINTENANCE", "ONLINE"),
        ("OTHER", "ONLINE"),
    }

    def detect_from_status_change(
        self,
        node_id: str,
        device_name: str,
        protocol: str,
        previous_status: str,
        current_status: str,
        connection_status: str = "",
        extra: Optional[Dict] = None,
    ) -> Optional[FaultEvent]:
        """
        วิเคราะห์การเปลี่ยน Status Transition แล้วคืน FaultEvent
        - ONLINE → OFFLINE = CRITICAL (อุปกรณ์ Down)
        - ONLINE → OTHER / connecting = WARNING (การเชื่อมต่อไม่เสถียร)
        - OFFLINE → ONLINE = RESOLVED (อุปกรณ์กลับมาออนไลน์)

        Returns:
            FaultEvent or None (ถ้า transition ไม่ interesting)
        """
        transition = (previous_status, current_status)

        # ── CRITICAL ──────────────────────────────────────
        if transition in self.CRITICAL_TRANSITIONS:
            fault_type = FaultType.DEVICE_DOWN
            if connection_status in ("unable-to-connect", "not-mounted", "not-in-inventory"):
                fault_type = FaultType.DEVICE_UNREACHABLE

            fe = FaultEvent(
                fault_type=fault_type,
                severity=FaultSeverity.CRITICAL,
                node_id=node_id,
                device_name=device_name,
                protocol=protocol,
                previous_status=previous_status,
                current_status=current_status,
                connection_status=connection_status,
                details=extra,
            )
            logger.warning(f"[FaultDetector] CRITICAL: {node_id} → {fault_type.value}")
            return fe

        # ── WARNING (connecting / degraded) ───────────────
        if transition in self.WARNING_TRANSITIONS or connection_status == "connecting":
            fe = FaultEvent(
                fault_type=FaultType.CONNECTION_DEGRADED,
                severity=FaultSeverity.WARNING,
                node_id=node_id,
                device_name=device_name,
                protocol=protocol,
                previous_status=previous_status,
                current_status=current_status,
                connection_status=connection_status,
                details=extra,
            )
            logger.info(f"[FaultDetector] WARNING: {node_id} — connection degraded")
            return fe

        # ── RESOLVED ──────────────────────────────────────
        if transition in self.RESOLVED_TRANSITIONS:
            fe = FaultEvent(
                fault_type=FaultType.DEVICE_RECOVERED,
                severity=FaultSeverity.RESOLVED,
                node_id=node_id,
                device_name=device_name,
                protocol=protocol,
                previous_status=previous_status,
                current_status=current_status,
                connection_status=connection_status,
                details=extra,
            )
            logger.info(f"[FaultDetector] RESOLVED: {node_id} recovered")
            return fe

        # Not interesting
        return None

    def detect_from_sync_result(self, sync_result: Dict[str, Any]) -> List[FaultEvent]:
        """
        วิเคราะห์ผลลัพธ์ของ Background Sync เพื่อหา Faults
        - ตรวจจาก synced items ที่มี status = OFFLINE
        - ตรวจจาก items ที่มี note = "Unmounted from ODL"
        - ตรวจจาก errors ในผล Sync

        ดูจาก synced items ที่มี status = OFFLINE (ก่อนหน้าอาจเป็น ONLINE)
        และ items ที่มี note = "Unmounted from ODL"
        """
        faults: List[FaultEvent] = []

        for item in sync_result.get("synced", []):
            if item.get("status") == "OFFLINE":
                note = item.get("note", "")
                fault_type = FaultType.DEVICE_UNMOUNTED if "Unmounted" in note else FaultType.DEVICE_DOWN

                faults.append(
                    FaultEvent(
                        fault_type=fault_type,
                        severity=FaultSeverity.CRITICAL,
                        node_id=item.get("node_id", "unknown"),
                        device_name=item.get("device_name", ""),
                        protocol="NETCONF",
                        previous_status="ONLINE",
                        current_status="OFFLINE",
                        connection_status=item.get("connection_status", ""),
                        details={"note": note},
                    )
                )

        for error in sync_result.get("errors", []):
            faults.append(
                FaultEvent(
                    fault_type=FaultType.SYNC_FAILED,
                    severity=FaultSeverity.WARNING,
                    node_id=error.get("node_id", "unknown"),
                    device_name="",
                    protocol="",
                    previous_status="",
                    current_status="",
                    connection_status="",
                    details=error,
                )
            )

        return faults
