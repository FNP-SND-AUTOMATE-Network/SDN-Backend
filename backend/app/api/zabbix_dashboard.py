"""
Zabbix Dashboard API
REST endpoints สำหรับ Frontend Dashboard ดึงข้อมูลจาก Zabbix SNMP Monitoring

Endpoints:
  GET /api/v1/zabbix/dashboard/health        — ตรวจสอบ Zabbix API connectivity
  GET /api/v1/zabbix/dashboard/overview       — สรุปภาพรวม (hosts, problems, severity)
  GET /api/v1/zabbix/dashboard/hosts          — รายการ hosts ทั้งหมด
  GET /api/v1/zabbix/dashboard/hosts/{id}     — รายละเอียด host + SNMP items
  GET /api/v1/zabbix/dashboard/hosts/{id}/traffic  — Traffic time-series
  GET /api/v1/zabbix/dashboard/hosts/{id}/snmp     — SNMP items overview
  GET /api/v1/zabbix/dashboard/problems       — Active problems
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from app.clients.zabbix_client import zabbix_client, ZabbixAPIError
from app.services.zabbix_monitoring_service import (
    PROBLEM_TIME_RANGE_SECONDS,
    zabbix_monitoring_service,
)
from app.core.logging import logger

router = APIRouter(
    prefix="/api/v1/zabbix/dashboard",
    tags=["Zabbix Dashboard"],
)


# ── Health Check ─────────────────────────────────────────────────

@router.get("/health")
async def zabbix_health_check():
    """
    ตรวจสอบการเชื่อมต่อ Zabbix API

    Returns:
        - status: "ok" / "error"
        - zabbix_version: เวอร์ชัน Zabbix
        - api_url: URL ที่ใช้เชื่อมต่อ
    """
    try:
        version = await zabbix_client.get_api_version()
        return {
            "status": "ok",
            "zabbix_version": version,
            "api_url": zabbix_client.api_url,
        }
    except ZabbixAPIError as e:
        logger.error(f"[ZabbixDashboard] Health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "api_url": zabbix_client.api_url,
        }
    except Exception as e:
        logger.error(f"[ZabbixDashboard] Health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "api_url": zabbix_client.api_url,
        }


# ── Dashboard Overview ───────────────────────────────────────────

@router.get("/overview")
async def get_dashboard_overview(
    time_range: Optional[str] = Query(
        "all",
        description="Time range filter: all, 1h, 1d, 1w, 1mo, 1y",
    ),
):
    """
    ภาพรวม Dashboard: จำนวน hosts, problems, severity breakdown

    สำหรับ Frontend แสดง:
    - จำนวน hosts ทั้งหมด / available / unavailable
    - จำนวน problems แยกตาม severity
    - รายชื่อ host groups
    """
    try:
        allowed_time_ranges = {"all", "1h", "1d", "1w", "1mo", "1y"}
        selected_time_range = (time_range or "all").strip().lower()
        if selected_time_range not in allowed_time_ranges:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Invalid time_range. Allowed values: all, 1h, 1d, 1w, 1mo, 1y"
                ),
            )

        return await zabbix_monitoring_service.get_dashboard_overview(
            time_range=selected_time_range,
        )
    except ZabbixAPIError as e:
        raise HTTPException(status_code=502, detail=f"Zabbix API error: {e.message}")


@router.get("/top-metrics")
async def get_dashboard_top_metrics(
    limit: int = Query(5, description="Number of top items to return", ge=1, le=20)
):
    """
    ดึงข้อมูล Top N แบบเรียลไทม์ (ใช้งานหนาแน่นที่สุด) สำหรับหน้า Dashboard
    ใช้ Zabbix Tag-based filtering (component: cpu / memory / network)
    ประกอบด้วย:
    - top_bandwidth (Interface traffic In/Out — tag: component=network)
    - top_cpu (Device CPU utilization — tag: component=cpu)
    - top_memory (Device RAM utilization — tag: component=memory)
    """
    try:
        return await zabbix_monitoring_service.get_top_metrics(limit=limit)
    except ZabbixAPIError as e:
        raise HTTPException(status_code=502, detail=f"Zabbix API error: {e.message}")

# ── Hosts ────────────────────────────────────────────────────────


@router.get("/hosts")
async def get_hosts(
    group_id: Optional[str] = Query(None, description="Filter by host group ID"),
    search: Optional[str] = Query(None, description="Search by host name"),
):
    """
    รายการ hosts ทั้งหมดที่ Zabbix monitor

    Returns array of hosts with:
    - hostid, hostname, name, status, availability
    - interfaces (agent, snmp, ipmi, jmx)
    - groups
    """
    try:
        hosts = await zabbix_monitoring_service.get_all_hosts(
            group_id=group_id,
            search=search,
        )
        return {"hosts": hosts, "total": len(hosts)}
    except ZabbixAPIError as e:
        raise HTTPException(status_code=502, detail=f"Zabbix API error: {e.message}")


# ── Host Detail ──────────────────────────────────────────────────

@router.get("/hosts/{host_id}")
async def get_host_detail(host_id: str):
    """
    รายละเอียด host เดียว:
    - ข้อมูล host + interfaces + templates
    - SNMP items ทั้งหมด + ค่าล่าสุด
    - Active problems ของ host นี้
    """
    try:
        detail = await zabbix_monitoring_service.get_host_detail(host_id)
        if "error" in detail:
            raise HTTPException(status_code=404, detail=detail["error"])
        return detail
    except ZabbixAPIError as e:
        raise HTTPException(status_code=502, detail=f"Zabbix API error: {e.message}")


# ── Host Traffic (for Charts) ───────────────────────────────────

@router.get("/hosts/{host_id}/traffic")
async def get_host_traffic(
    host_id: str,
    period: int = Query(1, description="Period in hours (1, 6, 12, 24)", ge=1, le=168),
    interface: Optional[str] = Query(None, description="Filter by interface name"),
):
    """
    Traffic data สำหรับแสดงกราฟ

    ดึง ifInOctets, ifOutOctets, ifSpeed ย้อนหลังตาม period
    Returns time-series data ที่พร้อมใช้กับ chart library

    period:
    - 1 = 1 ชั่วโมงล่าสุด
    - 6 = 6 ชั่วโมง
    - 24 = 1 วัน
    - 168 = 1 สัปดาห์
    """
    try:
        return await zabbix_monitoring_service.get_host_traffic(
            host_id=host_id,
            period_hours=period,
            interface_name=interface,
        )
    except ZabbixAPIError as e:
        raise HTTPException(status_code=502, detail=f"Zabbix API error: {e.message}")


# ── SNMP Items Overview ─────────────────────────────────────────

@router.get("/hosts/{host_id}/snmp")
async def get_host_snmp_overview(host_id: str):
    """
    SNMP items overview ของ host:
    - จัดหมวดหมู่: interface, traffic, cpu, memory, disk, system
    - แต่ละ item มีค่าล่าสุด (lastvalue)

    ใช้สำหรับแสดง SNMP data ในหน้า Host Detail
    """
    try:
        return await zabbix_monitoring_service.get_snmp_overview(host_id)
    except ZabbixAPIError as e:
        raise HTTPException(status_code=502, detail=f"Zabbix API error: {e.message}")


# ── Problems ─────────────────────────────────────────────────────

@router.get("/problems/time-ranges")
async def get_problem_time_ranges():
    """
    รายการช่วงเวลาที่ frontend ใช้แสดง filter บน dashboard
    """
    return {
        "default": "1w",
        "options": [
            {"value": "1h", "label": "Last 1 hour", "seconds": PROBLEM_TIME_RANGE_SECONDS["1h"]},
            {"value": "1d", "label": "Last 1 day", "seconds": PROBLEM_TIME_RANGE_SECONDS["1d"]},
            {"value": "1w", "label": "Last 1 week", "seconds": PROBLEM_TIME_RANGE_SECONDS["1w"]},
            {"value": "1mo", "label": "Last 1 month", "seconds": PROBLEM_TIME_RANGE_SECONDS["1mo"]},
            {"value": "1y", "label": "Last 1 year", "seconds": PROBLEM_TIME_RANGE_SECONDS["1y"]},
            {"value": "all", "label": "All time", "seconds": None},
        ],
    }

@router.get("/problems")
async def get_problems(
    severity_min: int = Query(0, description="Min severity (0-5)", ge=0, le=5),
    host_id: Optional[str] = Query(None, description="Filter by host ID"),
    limit: int = Query(100, description="Max problems to return", ge=1, le=500),
    time_range: Optional[str] = Query(
        "1w",
        description="Time range filter: all, 1h, 1d, 1w, 1mo, 1y",
    ),
):
    """
    Active problems (unresolved triggers)

    severity levels:
    - 0 = Not classified
    - 1 = Information
    - 2 = Warning
    - 3 = Average
    - 4 = High
    - 5 = Disaster

    Returns problems list + severity breakdown counts

    time_range:
    - all = ไม่กรองเวลา
    - 1h = 1 ชั่วโมงล่าสุด
    - 1d = 1 วันล่าสุด
    - 1w = 1 สัปดาห์ล่าสุด
    - 1mo = 1 เดือนล่าสุด (30 วัน)
    - 1y = 1 ปีล่าสุด (365 วัน)
    """
    try:
        allowed_time_ranges = {"all", "1h", "1d", "1w", "1mo", "1y"}
        selected_time_range = (time_range or "1w").strip().lower()
        if selected_time_range not in allowed_time_ranges:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Invalid time_range. Allowed values: all, 1h, 1d, 1w, 1mo, 1y"
                ),
            )

        host_ids = [host_id] if host_id else None
        return await zabbix_monitoring_service.get_problems_summary(
            severity_min=severity_min,
            host_ids=host_ids,
            limit=limit,
            time_range=selected_time_range,
        )
    except ZabbixAPIError as e:
        raise HTTPException(status_code=502, detail=f"Zabbix API error: {e.message}")
