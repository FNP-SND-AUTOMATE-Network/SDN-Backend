"""
Alert Deduplicator — ป้องกัน alert ซ้ำระหว่าง Zabbix Pipeline กับ Internal Fault Pipeline

เมื่อ Zabbix ส่ง alert ของ host ใดเข้ามา จะบันทึก timestamp ไว้
ถ้า Internal Fault Detection จะส่ง Slack สำหรับ host เดียวกัน
แต่มี Zabbix alert มาแล้วภายใน 5 นาที → skip ไม่ส่งซ้ำ

Usage:
    from app.core.alert_dedup import alert_dedup

    # เมื่อ Zabbix alert เข้ามา
    alert_dedup.record_zabbix_alert("Core-Router-01")

    # ก่อน Internal Fault จะส่ง Slack
    if alert_dedup.is_recently_alerted_by_zabbix("Core-Router-01"):
        skip...  # Zabbix แจ้งไปแล้ว
"""

from datetime import datetime, timedelta
from typing import Dict
from app.core.logging import logger


class AlertDeduplicator:
    """
    Tracks recent Zabbix alerts per host to prevent duplicate
    notifications from the Internal Fault Detection pipeline.
    """

    DEFAULT_WINDOW_SEC = 300  # 5 minutes

    def __init__(self):
        # host_key → last alert timestamp
        self._zabbix_alerts: Dict[str, datetime] = {}

    def record_zabbix_alert(self, host_key: str) -> None:
        """
        Record that Zabbix has sent an alert for this host.

        Args:
            host_key: host identifier (host_name or host_ip)
        """
        now = datetime.utcnow()
        self._zabbix_alerts[host_key] = now
        logger.debug(f"[AlertDedup] Recorded Zabbix alert for '{host_key}' at {now.isoformat()}")

        # Housekeep: remove entries older than 10 minutes
        self._cleanup(max_age_sec=600)

    def is_recently_alerted_by_zabbix(
        self,
        host_key: str,
        window_sec: int = DEFAULT_WINDOW_SEC,
    ) -> bool:
        """
        Check if Zabbix already sent an alert for this host
        within the specified time window.

        Args:
            host_key: host identifier to check
            window_sec: dedup window in seconds (default 300 = 5 min)

        Returns:
            True if Zabbix alerted recently → internal alert should be skipped
        """
        last_alert = self._zabbix_alerts.get(host_key)
        if last_alert is None:
            return False

        elapsed = (datetime.utcnow() - last_alert).total_seconds()
        if elapsed <= window_sec:
            logger.info(
                f"[AlertDedup] Host '{host_key}' was alerted by Zabbix "
                f"{elapsed:.0f}s ago (within {window_sec}s window) → SKIP internal alert"
            )
            return True

        return False

    def _cleanup(self, max_age_sec: int = 600) -> None:
        """Remove stale entries older than max_age_sec."""
        cutoff = datetime.utcnow() - timedelta(seconds=max_age_sec)
        stale_keys = [k for k, v in self._zabbix_alerts.items() if v < cutoff]
        for key in stale_keys:
            del self._zabbix_alerts[key]


# ── Singleton ────────────────────────────────────────────────────
alert_dedup = AlertDeduplicator()
