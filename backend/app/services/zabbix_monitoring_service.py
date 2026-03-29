"""
Zabbix Monitoring Service
Business logic layer สำหรับดึงข้อมูล SNMP/monitoring จาก Zabbix API
แล้วจัดรูปแบบให้พร้อมใช้บน Frontend Dashboard

Flow:
  Frontend → REST API → ZabbixMonitoringService → ZabbixClient → Zabbix JSON-RPC API
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from app.clients.zabbix_client import zabbix_client, ZabbixAPIError
from app.core.logging import logger


# ── Severity mapping (reuse concept from normalizer) ─────────────
SEVERITY_MAP = {
    "0": {"label": "Not classified", "color": "#97AAB3", "emoji": "⚪"},
    "1": {"label": "Information", "color": "#7499FF", "emoji": "🔵"},
    "2": {"label": "Warning", "color": "#FFC859", "emoji": "🟡"},
    "3": {"label": "Average", "color": "#FFA059", "emoji": "🟠"},
    "4": {"label": "High", "color": "#E97659", "emoji": "🔴"},
    "5": {"label": "Disaster", "color": "#E45959", "emoji": "🔥"},
}

# Host availability values
AVAILABILITY_MAP = {
    "0": "unknown",
    "1": "available",
    "2": "unavailable",
}

# Interface type
INTERFACE_TYPE_MAP = {
    "1": "agent",
    "2": "snmp",
    "3": "ipmi",
    "4": "jmx",
}


class ZabbixMonitoringService:
    """
    High-level service สำหรับ Dashboard
    รวม logic ในการจัดรูปแบบข้อมูลจาก Zabbix API
    """

    def __init__(self):
        # Small in-memory cache to reduce repetitive polling load from frontend.
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _cache_get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if not entry:
            return None
        if entry["expires_at"] < time.time():
            self._cache.pop(key, None)
            return None
        return entry["value"]

    def _cache_set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._cache[key] = {
            "value": value,
            "expires_at": time.time() + ttl_seconds,
        }

    # ── Dashboard Overview ───────────────────────────────────────

    async def get_dashboard_overview(self) -> Dict[str, Any]:
        """
        สรุปภาพรวม Dashboard: จำนวน hosts, problems, severity breakdown
        ใช้แสดงหน้า Dashboard หลัก
        """
        cached = self._cache_get("overview")
        if cached is not None:
            return cached

        try:
            hosts, problems, host_groups = await asyncio.gather(
                zabbix_client.get_hosts(),
                zabbix_client.get_problems(),
                zabbix_client.get_host_groups(),
            )

            # Count hosts by availability
            # Zabbix 7.x: availability อยู่ใน interface, ไม่ใช่ host-level
            hosts_available = 0
            hosts_unavailable = 0
            hosts_unknown = 0
            for h in hosts:
                # Check interfaces for availability (Zabbix 7.x)
                ifaces = h.get("interfaces", [])
                if ifaces:
                    has_available = any(str(i.get("available", "0")) == "1" for i in ifaces)
                    has_unavailable = any(str(i.get("available", "0")) == "2" for i in ifaces)
                    if has_unavailable:
                        hosts_unavailable += 1
                    elif has_available:
                        hosts_available += 1
                    else:
                        hosts_unknown += 1
                else:
                    hosts_unknown += 1

            # Count problems by severity
            severity_counts = {str(i): 0 for i in range(6)}
            for p in problems:
                sev = str(p.get("severity", "0"))
                severity_counts[sev] = severity_counts.get(sev, 0) + 1

            severity_breakdown = []
            for sev_id, count in severity_counts.items():
                meta = SEVERITY_MAP.get(sev_id, SEVERITY_MAP["0"])
                severity_breakdown.append({
                    "severity": int(sev_id),
                    "label": meta["label"],
                    "color": meta["color"],
                    "emoji": meta["emoji"],
                    "count": count,
                })

            result = {
                "hosts": {
                    "total": len(hosts),
                    "available": hosts_available,
                    "unavailable": hosts_unavailable,
                    "unknown": hosts_unknown,
                },
                "problems": {
                    "total": len(problems),
                    "severity_breakdown": severity_breakdown,
                },
                "host_groups": [
                    {"groupid": g["groupid"], "name": g["name"]}
                    for g in host_groups
                ],
                "timestamp": int(time.time()),
            }
            self._cache_set("overview", result, ttl_seconds=20)
            return result

        except ZabbixAPIError as e:
            logger.error(f"[ZabbixMonitor] Dashboard overview failed: {e}")
            raise

    # ── Hosts ────────────────────────────────────────────────────

    async def get_all_hosts(
        self,
        group_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        ดึง hosts ทั้งหมด พร้อม format ข้อมูลให้อ่านง่าย
        """
        cache_key = f"hosts:{group_id or ''}:{search or ''}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        group_ids = [group_id] if group_id else None
        hosts = await zabbix_client.get_hosts(group_ids=group_ids, search=search)

        result = []
        for h in hosts:
            interfaces = []
            host_availability = "unknown"
            for iface in h.get("interfaces", []):
                iface_avail = AVAILABILITY_MAP.get(str(iface.get("available", "0")), "unknown")
                iface_type = INTERFACE_TYPE_MAP.get(str(iface.get("type", "")), "unknown")
                interfaces.append({
                    "interfaceid": iface.get("interfaceid"),
                    "ip": iface.get("ip"),
                    "dns": iface.get("dns"),
                    "port": iface.get("port"),
                    "type": iface_type,
                    "main": iface.get("main") == "1",
                    "available": iface_avail,
                })
                # Derive host-level availability from interfaces
                if iface_avail == "available":
                    host_availability = "available"
                elif iface_avail == "unavailable" and host_availability != "available":
                    host_availability = "unavailable"

            # Get SNMP interface availability
            snmp_avail = "unknown"
            for iface in interfaces:
                if iface["type"] == "snmp":
                    snmp_avail = iface["available"]
                    break

            result.append({
                "hostid": h["hostid"],
                "hostname": h.get("host", ""),
                "name": h.get("name", ""),
                "status": "enabled" if h.get("status") == "0" else "disabled",
                "availability": host_availability,
                "snmp_availability": snmp_avail,
                "description": h.get("description", ""),
                "interfaces": interfaces,
                "groups": [
                    {"groupid": g["groupid"], "name": g["name"]}
                    for g in h.get("hostgroups", h.get("groups", []))
                ],
            })

        self._cache_set(cache_key, result, ttl_seconds=20)
        return result

    # ── Host Detail ──────────────────────────────────────────────

    async def get_host_detail(self, host_id: str) -> Dict[str, Any]:
        """
        รายละเอียด host + items (SNMP) ทั้งหมด + ค่าล่าสุด
        """
        host = await zabbix_client.get_host(host_id)
        if not host:
            return {"error": "Host not found", "host_id": host_id}

        # Get all items for this host
        all_items = await zabbix_client.get_items(host_id)

        # Categorize items
        snmp_items = []
        other_items = []
        for item in all_items:
            formatted_item = {
                "itemid": item["itemid"],
                "name": item.get("name", ""),
                "key": item.get("key_", ""),
                "type": int(item.get("type", 0)),
                "value_type": int(item.get("value_type", 0)),
                "lastvalue": item.get("lastvalue", ""),
                "lastclock": item.get("lastclock", ""),
                "units": item.get("units", ""),
                "description": item.get("description", ""),
                "status": "enabled" if item.get("status") == "0" else "disabled",
                "state": "normal" if item.get("state") == "0" else "not_supported",
                "error": item.get("error", ""),
            }

            # SNMP types: 4 (old), 20 (new Zabbix 6.0+)
            if int(item.get("type", 0)) in (4, 20):
                snmp_items.append(formatted_item)
            else:
                other_items.append(formatted_item)

        # Get active problems for this host
        problems = await zabbix_client.get_problems(host_ids=[host_id])

        return {
            "host": {
                "hostid": host["hostid"],
                "hostname": host.get("host", ""),
                "name": host.get("name", ""),
                "status": "enabled" if host.get("status") == "0" else "disabled",
                "availability": AVAILABILITY_MAP.get(str(host.get("available", "0")), "unknown"),
                "description": host.get("description", ""),
                "interfaces": host.get("interfaces", []),
                "groups": host.get("hostgroups", host.get("groups", [])),
                "templates": host.get("parentTemplates", []),
            },
            "items": {
                "total": len(all_items),
                "snmp_count": len(snmp_items),
                "snmp_items": snmp_items,
                "other_items": other_items[:50],  # Limit non-SNMP items
            },
            "problems": [
                {
                    "eventid": p.get("eventid"),
                    "severity": int(p.get("severity", 0)),
                    "severity_label": SEVERITY_MAP.get(str(p.get("severity", "0")), {}).get("label", "Unknown"),
                    "name": p.get("name", ""),
                    "clock": p.get("clock", ""),
                    "acknowledged": p.get("acknowledged") == "1",
                }
                for p in problems
            ],
        }

    # ── Traffic Data (Interface SNMP) ────────────────────────────

    @staticmethod
    def _format_bps(bps: float) -> Dict[str, Any]:
        """แปลงค่า bps ดิบให้อ่านง่าย พร้อม auto-select unit"""
        if bps >= 1_000_000_000:
            return {"value": round(bps / 1_000_000_000, 2), "unit": "Gbps"}
        elif bps >= 1_000_000:
            return {"value": round(bps / 1_000_000, 2), "unit": "Mbps"}
        elif bps >= 1_000:
            return {"value": round(bps / 1_000, 2), "unit": "Kbps"}
        else:
            return {"value": round(bps, 2), "unit": "bps"}

    async def get_host_traffic(
        self,
        host_id: str,
        period_hours: int = 1,
        interface_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        ดึงข้อมูล traffic ของ interfaces สำหรับแสดงกราฟ Traffic บน Dashboard

        Response format:
        - clock: Unix timestamp (วินาที) + datetime (ISO 8601 อ่านง่าย)
        - value_bps: ค่าดิบเป็น bits per second
        - value_formatted: ค่าที่แปลงหน่วยแล้ว (เช่น "2.85 Kbps")
        """
        cache_key = f"traffic:{host_id}:{period_hours}:{interface_name or ''}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # Search for traffic-related SNMP items
        all_items = await zabbix_client.get_items(host_id)

        # Filter items ที่เกี่ยวกับ network traffic
        traffic_keys = [
            "net.if.in", "net.if.out", "net.if.speed",
            "ifInOctets", "ifOutOctets", "ifHCInOctets", "ifHCOutOctets",
            "ifSpeed", "ifHighSpeed", "ifOperStatus", "ifAdminStatus",
            "ifAlias", "ifDescr",
        ]

        traffic_items = []
        for item in all_items:
            key = item.get("key_", "")
            name = item.get("name", "").lower()

            # Match traffic-related keys
            is_traffic = any(tk.lower() in key.lower() or tk.lower() in name for tk in traffic_keys)
            if interface_name:
                is_traffic = is_traffic and interface_name.lower() in name.lower()

            if is_traffic:
                traffic_items.append(item)

        if not traffic_items:
            result = {
                "host_id": host_id,
                "interfaces": [],
                "message": "ไม่พบข้อมูล traffic สำหรับ host นี้ — อาจยังไม่มี SNMP interface ถูก monitor",
            }
            self._cache_set(cache_key, result, ttl_seconds=15)
            return result

        # Get history for traffic items
        time_from = int(time.time()) - (period_hours * 3600)
        item_ids = [it["itemid"] for it in traffic_items]

        # Fetch numeric float (0) and numeric unsigned (3)
        history_float = await zabbix_client.get_history(
            item_ids=item_ids,
            history_type=0,
            time_from=time_from,
            limit=1000,
            sort_order="ASC",
        )
        history_uint = await zabbix_client.get_history(
            item_ids=item_ids,
            history_type=3,
            time_from=time_from,
            limit=1000,
            sort_order="ASC",
        )

        # Combine history
        all_history = history_float + history_uint

        # Group history by item
        history_by_item: Dict[str, List] = {}
        for h in all_history:
            iid = h.get("itemid", "")
            if iid not in history_by_item:
                history_by_item[iid] = []

            raw_val = h.get("value", "0")
            try:
                bps = float(raw_val) if raw_val else 0.0
            except ValueError:
                bps = 0.0

            clock = int(h.get("clock", 0))
            formatted = self._format_bps(bps)

            # แปลง Unix timestamp → datetime ที่มนุษย์อ่านได้ (Asia/Bangkok = UTC+7)
            dt = datetime.fromtimestamp(clock, tz=timezone(timedelta(hours=7)))

            history_by_item[iid].append({
                "clock": clock,
                "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "value_bps": bps,
                "display": f"{formatted['value']} {formatted['unit']}",
            })

        # Build interface traffic data with summary
        interfaces_data = []
        for item in traffic_items:
            iid = item["itemid"]
            history = history_by_item.get(iid, [])

            # Parse lastvalue
            try:
                last_bps = float(item.get("lastvalue", "0"))
            except ValueError:
                last_bps = 0.0
            last_formatted = self._format_bps(last_bps)

            # Compute summary stats from history
            bps_values = [h["value_bps"] for h in history if h["value_bps"] > 0]
            summary = None
            if bps_values:
                avg_bps = sum(bps_values) / len(bps_values)
                max_bps = max(bps_values)
                min_bps = min(bps_values)
                summary = {
                    "avg": self._format_bps(avg_bps),
                    "max": self._format_bps(max_bps),
                    "min": self._format_bps(min_bps),
                    "data_points": len(history),
                }

            interfaces_data.append({
                "itemid": iid,
                "name": item.get("name", ""),
                "key": item.get("key_", ""),
                "units": item.get("units", ""),
                "lastvalue": {
                    "raw_bps": last_bps,
                    "display": f"{last_formatted['value']} {last_formatted['unit']}",
                },
                "summary": summary,
                "history": history,
            })

        result = {
            "host_id": host_id,
            "period_hours": period_hours,
            "time_from": time_from,
            "time_till": int(time.time()),
            "interfaces": interfaces_data,
            "_meta": {
                "description": "ข้อมูล traffic ของแต่ละ interface",
                "history_fields": {
                    "clock": "Unix timestamp (วินาที)",
                    "datetime": "วันที่-เวลา ที่อ่านง่าย (เขตเวลา Bangkok UTC+7)",
                    "value_bps": "ค่าดิบเป็น bits per second (bps) สำหรับคำนวณ",
                    "display": "ค่าที่แปลงหน่วยแล้วพร้อมแสดง เช่น '2.42 Kbps'",
                },
                "lastvalue": "ค่าล่าสุดที่ Zabbix อ่านได้ (raw_bps + display)",
                "summary": "สถิติสรุป: ค่าเฉลี่ย (avg), สูงสุด (max), ต่ำสุด (min)",
            },
        }
        self._cache_set(cache_key, result, ttl_seconds=15)
        return result

    # ── Problems Summary ─────────────────────────────────────────

    async def get_problems_summary(
        self,
        severity_min: int = 0,
        host_ids: Optional[List[str]] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Active problems with enriched severity info
        """
        problems = await zabbix_client.get_problems(
            severity_min=severity_min,
            host_ids=host_ids,
            limit=limit,
        )

        # Enrich with trigger/host info
        enriched = []
        bkk_tz = timezone(timedelta(hours=7))
        for p in problems:
            sev = str(p.get("severity", "0"))
            meta = SEVERITY_MAP.get(sev, SEVERITY_MAP["0"])

            # แปลง clock → datetime ที่มนุษย์อ่านได้
            clock_raw = p.get("clock", "")
            try:
                clock_int = int(clock_raw) if clock_raw else 0
                dt = datetime.fromtimestamp(clock_int, tz=bkk_tz)
                dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError):
                dt_str = ""

            enriched.append({
                "eventid": p.get("eventid"),
                "objectid": p.get("objectid"),
                "name": p.get("name", ""),
                "severity": int(sev),
                "severity_label": meta["label"],
                "severity_color": meta["color"],
                "severity_emoji": meta["emoji"],
                "clock": clock_raw,
                "datetime": dt_str,
                "acknowledged": p.get("acknowledged") == "1",
                "tags": p.get("tags", []),
            })

        # Count by severity
        severity_counts = {str(i): 0 for i in range(6)}
        for p in enriched:
            sev = str(p["severity"])
            severity_counts[sev] += 1

        return {
            "total": len(enriched),
            "severity_counts": severity_counts,
            "problems": enriched,
        }

    # ── SNMP Items Overview ──────────────────────────────────────

    async def get_snmp_overview(self, host_id: str) -> Dict[str, Any]:
        """
        สรุป SNMP items ทั้งหมดของ host — grouped by category
        """
        cache_key = f"snmp:{host_id}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        snmp_items = await zabbix_client.get_snmp_items(host_id)

        # Categorize by item key pattern
        categories = {
            "interface": [],      # ifDescr, ifOperStatus, ifSpeed
            "traffic": [],        # ifInOctets, ifOutOctets
            "cpu": [],            # hrProcessorLoad, ssCpuIdle
            "memory": [],         # hrStorageUsed, memTotalReal
            "disk": [],           # hrStorageSize, hrStorageUsed
            "system": [],         # sysUpTime, sysDescr, sysName
            "other": [],
        }

        for item in snmp_items:
            key = item.get("key_", "").lower()
            name = item.get("name", "").lower()

            formatted = {
                "itemid": item["itemid"],
                "name": item.get("name", ""),
                "key": item.get("key_", ""),
                "lastvalue": item.get("lastvalue", ""),
                "units": item.get("units", ""),
                "lastclock": item.get("lastclock", ""),
            }

            if any(k in key or k in name for k in ["ifinoctets", "ifoutoctets", "ifhcinoctets", "ifhcoutoctets", "net.if.in", "net.if.out"]):
                categories["traffic"].append(formatted)
            elif any(k in key or k in name for k in ["ifoperstatus", "ifadminstatus", "ifdescr", "ifalias", "ifspeed"]):
                categories["interface"].append(formatted)
            elif any(k in key or k in name for k in ["cpu", "processor", "load"]):
                categories["cpu"].append(formatted)
            elif any(k in key or k in name for k in ["memory", "mem", "swap", "buffer"]):
                categories["memory"].append(formatted)
            elif any(k in key or k in name for k in ["disk", "storage", "filesystem"]):
                categories["disk"].append(formatted)
            elif any(k in key or k in name for k in ["sysuptime", "sysdescr", "sysname", "syslocation", "syscontact"]):
                categories["system"].append(formatted)
            else:
                categories["other"].append(formatted)

        result = {
            "host_id": host_id,
            "total_snmp_items": len(snmp_items),
            "categories": categories,
        }
        self._cache_set(cache_key, result, ttl_seconds=20)
        return result


    # ── Top Metrics Dashboard ──────────────────────────────────────

    async def get_top_metrics(self, limit: int = 5) -> Dict[str, Any]:
        """
        วิเคราะห์และดึงค่า Top N (Bandwidth, CPU, Memory, Uptime)
        ใช้ Zabbix Tag-based filtering (component: cpu / memory / network)
        """
        cache_key = f"top_metrics:{limit}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # 1. Get all active hosts
        hosts = await self.get_all_hosts()
        active_hosts = [h for h in hosts if h["status"] == "enabled"]
        host_ids = [h["hostid"] for h in active_hosts]
        host_map = {h["hostid"]: h["hostname"] for h in active_hosts}

        if not host_ids:
            return {"top_cpu": [], "top_memory": [], "top_bandwidth": []}

        # 2. Fetch items by tag (parallel) — ใช้ tag "component" ที่ Zabbix Template กำหนดไว้
        cpu_items, memory_items, network_items = await asyncio.gather(
            zabbix_client.get_items_by_tag(host_ids, tag="component", value="cpu"),
            zabbix_client.get_items_by_tag(host_ids, tag="component", value="memory"),
            zabbix_client.get_items_by_tag(host_ids, tag="component", value="network"),
        )

        logger.info(
            f"[ZabbixMonitor] Tag-based items — "
            f"CPU: {len(cpu_items)}, Memory: {len(memory_items)}, Network: {len(network_items)}"
        )

        # ── 3a. Process CPU items ────────────────────────────────
        top_cpu = []
        for item in cpu_items:
            hostid = item.get("hostid")
            if not hostid:
                continue
            hostname = host_map.get(str(hostid), f"Host {hostid}")
            lastvalue = item.get("lastvalue", "0")
            try:
                val = float(lastvalue) if lastvalue else 0.0
            except ValueError:
                val = 0.0
            if val <= 0:
                continue
            # Accept items that look like percentage utilization
            units = item.get("units", "")
            if "%" in units or "utilization" in item.get("name", "").lower():
                top_cpu.append({
                    "host": hostname,
                    "name": item.get("name"),
                    "value": round(val, 2),
                    "unit": "%",
                })

        # ── 3b. Process Memory items ─────────────────────────────
        # Memory tag returns many items (Free, Used, Total, Utilization, etc.)
        # กรองเอาเฉพาะ Utilization หรือ Used (percentage)
        top_memory = []
        for item in memory_items:
            hostid = item.get("hostid")
            if not hostid:
                continue
            hostname = host_map.get(str(hostid), f"Host {hostid}")
            name_lower = item.get("name", "").lower()
            units = item.get("units", "")

            # กรอง: เอาเฉพาะ Memory utilization / Memory used percentage
            is_utilization = any(kw in name_lower for kw in [
                "utilization", "memory used", "pused",
                "used percentage", "usage percentage",
            ])
            if not is_utilization and "%" not in units:
                continue

            lastvalue = item.get("lastvalue", "0")
            try:
                val = float(lastvalue) if lastvalue else 0.0
            except ValueError:
                val = 0.0
            if val <= 0:
                continue

            top_memory.append({
                "host": hostname,
                "name": item.get("name"),
                "value": round(val, 2),
                "unit": units if units else "%",
            })

        # ── 3c. Process Network (Bandwidth) items ────────────────
        # Network tag returns ทุก Interface ทั้ง In/Out — เรา sort หา Top Bandwidth
        # กรองเฉพาะ "Bits received" / "Bits sent" (ชื่อ item) หรือ key "net.if.*"
        #
        # ⚠ ค่าที่ Zabbix คืนมาเป็น bps (bits per second) อยู่แล้ว
        #   → หาร 1,000,000 = Mbps  |  หาร 1,000,000,000 = Gbps
        #   ไม่ต้องคูณ 8 (ไม่ใช่ octets/bytes)
        top_traffic = []
        for item in network_items:
            hostid = item.get("hostid")
            if not hostid:
                continue
            hostname = host_map.get(str(hostid), f"Host {hostid}")
            key = item.get("key_", "").lower()
            name_lower = item.get("name", "").lower()

            # กรองเฉพาะ traffic items:
            #   วิธี 1 — key ขึ้นต้นด้วย net.if.  (แม่นยำที่สุด)
            #   วิธี 2 — ชื่อ item มีคำว่า "bits received" / "bits sent"
            is_traffic = (
                key.startswith("net.if.in") or key.startswith("net.if.out")
                or "bits received" in name_lower
                or "bits sent" in name_lower
            )
            if not is_traffic:
                continue

            lastvalue = item.get("lastvalue", "0")
            try:
                val = float(lastvalue) if lastvalue else 0.0
            except ValueError:
                val = 0.0
            if val <= 0:
                continue

            # ค่าจาก Zabbix เป็น bps อยู่แล้ว → แปลงเป็น Mbps
            mbps = val / 1_000_000

            if mbps < 0.01:  # Skip negligible traffic
                continue

            # Auto-select readable unit
            if mbps >= 1000:
                display_value = round(mbps / 1000, 2)
                display_unit = "Gbps"
            else:
                display_value = round(mbps, 2)
                display_unit = "Mbps"

            # Determine direction
            direction = "Inbound"
            if "net.if.out" in key or "bits sent" in name_lower or "out" in key:
                direction = "Outbound"

            # Extract interface name (e.g. "Ethernet1/0/1: Bits received" → "Ethernet1/0/1")
            raw_name = item.get("name", "")
            interface_name = (
                raw_name
                .replace("Bits received", "")
                .replace("Bits sent", "")
                .replace("Interface", "")
                .strip(": ")
            )

            top_traffic.append({
                "host": hostname,
                "interface": interface_name,
                "direction": direction,
                "value_bps": round(val, 0),       # ค่าดิบ bps เก็บไว้ใช้ sort
                "value": display_value,
                "unit": display_unit,
            })

        # ── 4. Sort & deduplicate ────────────────────────────────
        # Sort by raw bps for accurate ranking, then strip internal field
        top_traffic = sorted(top_traffic, key=lambda x: x["value_bps"], reverse=True)[:limit]
        for t in top_traffic:
            del t["value_bps"]  # ไม่ต้องส่ง bps ดิบไป Frontend

        # Deduplicate CPU (take highest per host)
        top_cpu_dedup = []
        for c in sorted(top_cpu, key=lambda x: x["value"], reverse=True):
            if not any(x["host"] == c["host"] for x in top_cpu_dedup):
                top_cpu_dedup.append(c)
                if len(top_cpu_dedup) >= limit:
                    break

        # Deduplicate Memory (take highest per host)
        top_mem_dedup = []
        for m in sorted(top_memory, key=lambda x: x["value"], reverse=True):
            if not any(x["host"] == m["host"] for x in top_mem_dedup):
                top_mem_dedup.append(m)
                if len(top_mem_dedup) >= limit:
                    break

        result = {
            "top_cpu": top_cpu_dedup,
            "top_memory": top_mem_dedup,
            "top_bandwidth": top_traffic,
        }

        self._cache_set(cache_key, result, ttl_seconds=30)
        return result


# ── Singleton ────────────────────────────────────────────────────
zabbix_monitoring_service = ZabbixMonitoringService()
