"""
Zabbix Monitoring Service
Business logic layer สำหรับดึงข้อมูล SNMP/monitoring จาก Zabbix API
แล้วจัดรูปแบบให้พร้อมใช้บน Frontend Dashboard

Flow:
  Frontend → REST API → ZabbixMonitoringService → ZabbixClient → Zabbix JSON-RPC API
"""

import asyncio
import re
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

# Dashboard problem filtering presets.
PROBLEM_TIME_RANGE_SECONDS = {
    "1h": 60 * 60,
    "1d": 24 * 60 * 60,
    "1w": 7 * 24 * 60 * 60,
    "1mo": 30 * 24 * 60 * 60,
    "1y": 365 * 24 * 60 * 60,
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

    async def get_dashboard_overview(self, time_range: Optional[str] = None) -> Dict[str, Any]:
        """
        สรุปภาพรวม Dashboard: จำนวน hosts, problems, severity breakdown
        ใช้แสดงหน้า Dashboard หลัก
        """
        selected_time_range = (time_range or "all").strip().lower()
        time_from: Optional[int] = None
        if selected_time_range in PROBLEM_TIME_RANGE_SECONDS:
            time_from = int(time.time()) - PROBLEM_TIME_RANGE_SECONDS[selected_time_range]

        cache_key = f"overview:{selected_time_range}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            hosts, problems, host_groups = await asyncio.gather(
                zabbix_client.get_hosts(),
                zabbix_client.get_problems(time_from=time_from),
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
                    "time_range": selected_time_range,
                    "severity_breakdown": severity_breakdown,
                },
                "host_groups": [
                    {"groupid": g["groupid"], "name": g["name"]}
                    for g in host_groups
                ],
                "timestamp": int(time.time()),
            }
            self._cache_set(cache_key, result, ttl_seconds=20)
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

    @staticmethod
    def _is_traffic_item(item: Dict[str, Any]) -> bool:
        """ตรวจว่า item เป็นค่า network traffic (in/out throughput) หรือไม่"""
        key = str(item.get("key_", "")).lower()
        name_lower = str(item.get("name", "")).lower()
        return (
            key.startswith("net.if.in")
            or key.startswith("net.if.out")
            or "bits received" in name_lower
            or "bits sent" in name_lower
            or "ifhcinoctets" in key
            or "ifhcoutoctets" in key
            or "ifinoctets" in key
            or "ifoutoctets" in key
        )

    @staticmethod
    def _detect_traffic_direction(item: Dict[str, Any]) -> str:
        """เดาทิศทาง traffic จาก key/name ของ Zabbix item"""
        key = str(item.get("key_", "")).lower()
        name_lower = str(item.get("name", "")).lower()
        if (
            key.startswith("net.if.out")
            or "bits sent" in name_lower
            or "ifhcoutoctets" in key
            or "ifoutoctets" in key
        ):
            return "Outbound"
        return "Inbound"

    @staticmethod
    def _extract_interface_index(item: Dict[str, Any]) -> Optional[str]:
        """ดึง SNMP interface index จาก key/name เช่น .1, .2"""
        key = str(item.get("key_", ""))
        name = str(item.get("name", ""))

        for source in [key, name]:
            bracket_match = re.search(r"\[(?:[^\]]*\.)?(\d+)\]", source, flags=re.IGNORECASE)
            if bracket_match:
                return bracket_match.group(1)

            dot_match = re.search(r"\.(\d+)$", source)
            if dot_match:
                return dot_match.group(1)

        return None

    @classmethod
    def _build_interface_name_map_from_items(cls, items: List[Dict[str, Any]]) -> Dict[str, str]:
        """สร้าง map index -> ชื่อ interface (ifName/ifDescr/ifAlias)"""
        name_map: Dict[str, str] = {}

        for item in items:
            key_lower = str(item.get("key_", "")).lower()
            looks_like_label_item = (
                "ifname" in key_lower
                or "ifdescr" in key_lower
                or "ifalias" in key_lower
            )
            if not looks_like_label_item:
                continue

            idx = cls._extract_interface_index(item)
            if not idx:
                continue

            raw_candidates = [
                str(item.get("name", "")).strip(),
                str(item.get("lastvalue", "")).strip(),
            ]

            candidate = ""
            for raw in raw_candidates:
                if not raw:
                    continue
                cleaned = (
                    raw
                    .replace("Interface", "")
                    .replace("Bits received", "")
                    .replace("Bits sent", "")
                    .strip(": ")
                )
                # Skip pure numeric values (e.g. ifSpeed=1000000000) and OID-like names.
                if cleaned.isdigit():
                    continue
                if cleaned and not re.match(r"^if(?:hc)?(?:in|out)octets\.\d+$", cleaned, flags=re.IGNORECASE):
                    candidate = cleaned
                    break

            if candidate:
                name_map[idx] = candidate

        return name_map

    @classmethod
    def _extract_interface_name(cls, item: Dict[str, Any], interface_name_map: Optional[Dict[str, str]] = None) -> str:
        """แปลงชื่อ item/key ให้เหลือ interface name ที่เทียบข้าม endpoint ได้"""
        key = str(item.get("key_", ""))
        key_lower = key.lower()
        interface_name_map = interface_name_map or {}

        raw_name = str(item.get("name", ""))
        # Prefer human-readable label from item name when available
        # e.g. "Interface Gi1(): Bits received" -> "Gi1()"
        m = re.search(r"interface\s+(.+?)\s*:\s*(bits received|bits sent)", raw_name, flags=re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if candidate and not candidate.isdigit():
                return candidate

        if key_lower.startswith("net.if.in[") or key_lower.startswith("net.if.out["):
            start = key.find("[")
            end = key.find("]", start + 1)
            if start >= 0 and end > start:
                inside = key[start + 1:end]
                iface = inside.split(",")[0].strip().strip('"').strip("'")
                if iface:
                    idx_from_iface = re.search(r"(?:if(?:hc)?(?:in|out)octets\.)(\d+)$", iface, flags=re.IGNORECASE)
                    if idx_from_iface and idx_from_iface.group(1) in interface_name_map:
                        return interface_name_map[idx_from_iface.group(1)]
                    return iface

        iface = (
            raw_name
            .replace("Bits received", "")
            .replace("Bits sent", "")
            .replace("Interface", "")
            .strip(": ")
        )

        # Some templates expose raw SNMP item names like ifHCOutOctets.1.
        # Convert these to a readable port label.
        oid_like = re.match(r"^if(?:hc)?(?:in|out)octets\.(\d+)$", iface, flags=re.IGNORECASE)
        if oid_like:
            idx = oid_like.group(1)
            if idx in interface_name_map:
                return interface_name_map[idx]
            return f"Port {oid_like.group(1)}"

        # Fallback: parse index from key forms like ifHCOutOctets.1 / ifInOctets.2
        key_oid_like = re.search(r"if(?:hc)?(?:in|out)octets\.(\d+)", key, flags=re.IGNORECASE)
        if key_oid_like:
            idx = key_oid_like.group(1)
            if idx in interface_name_map:
                return interface_name_map[idx]
            return f"Port {key_oid_like.group(1)}"

        idx = cls._extract_interface_index(item)
        if idx and idx in interface_name_map:
            return interface_name_map[idx]

        return iface

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

        interface_name_map = self._build_interface_name_map_from_items(all_items)

        # Get history for traffic items
        time_from = int(time.time()) - (period_hours * 3600)
        item_ids = [it["itemid"] for it in traffic_items]

        # Fetch numeric float (0) and numeric unsigned (3)
        # Increase limit from 1000 to 10000 because 15s polling interval on 20+ ports generates ~5000+ records/hour
        history_float = await zabbix_client.get_history(
            item_ids=item_ids,
            history_type=0,
            time_from=time_from,
            limit=10000,
            sort_order="ASC",
        )
        history_uint = await zabbix_client.get_history(
            item_ids=item_ids,
            history_type=3,
            time_from=time_from,
            limit=10000,
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

        # === Add formatting for MUI X-Charts ===
        # The frontend expects a shared 'timestamps' array and 'series' array.
        all_clocks = set()
        for iface in interfaces_data:
            for h in iface.get("history", []):
                all_clocks.add(h["clock"])
        
        timestamps = sorted(list(all_clocks))
        series = []
        
        for iface in interfaces_data:
            history = iface.get("history", [])
            if not history:
                continue # Skip interfaces with no data in this period
                
            # Create a lookup for fast matching
            history_map = {h["clock"]: h["value_bps"] for h in history}
            
            # Build data array corresponding to the shared timestamps axis
            # Use 0 for missing data points to ensure continuous line (no gaps)
            data_points = []
            for t in timestamps:
                data_points.append(history_map.get(t, 0))
                
            # Filter to only actual traffic/bandwidth items for the chart
            # We don't want to plot errors, discards, or status
            key_lower = iface.get("key", "").lower()
            name_lower = iface.get("name", "").lower()
            
            is_in_out_traffic = self._is_traffic_item({"key_": iface.get("key", ""), "name": iface.get("name", "")})
            
            is_noise = (
                "error" in name_lower or "discard" in name_lower 
                or "status" in name_lower or "speed" in name_lower
                or "discards" in key_lower or "errors" in key_lower
            )

            if is_in_out_traffic and not is_noise:
                # ใช้ parser เดียวกับ top-metrics เพื่อให้ชื่อ interface ตรงกันทุก endpoint
                parsed_name = self._extract_interface_name({"key_": iface.get("key", ""), "name": iface.get("name", "")}, interface_name_map)
                direction = "Out" if self._detect_traffic_direction({"key_": iface.get("key", ""), "name": iface.get("name", "")}) == "Outbound" else "In"
                label = f"{parsed_name}: {direction}" if parsed_name else iface.get("name", "")
                    
                # Compute peak traffic for sorting so we only show the "Top" lines
                max_traffic = max([v for v in data_points if v is not None] + [0])
                    
                series.append({
                    "label": label,
                    "data": data_points,
                    "_max_traffic": max_traffic
                })

        # --- Limit to Top 10 High-Traffic Series ---
        # Huawei and switches with many ports will crash the UI if we plot 50+ lines simultaneously.
        # Keeping only the 10 highest peak traffic lines.
        series = sorted(series, key=lambda x: x.get("_max_traffic", 0), reverse=True)[:10]
        for s in series:
            s.pop("_max_traffic", None)

        result = {
            "host_id": host_id,
            "period_hours": period_hours,
            "time_from": time_from,
            "time_till": int(time.time()),
            "interfaces": interfaces_data,
            "timestamps": timestamps,
            "series": series,
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
        page: int = 1,
        page_size: Optional[int] = None,
        time_range: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Active problems with enriched severity info
        """
        time_from: Optional[int] = None
        selected_time_range = (time_range or "1w").strip().lower()
        if selected_time_range in PROBLEM_TIME_RANGE_SECONDS:
            time_from = int(time.time()) - PROBLEM_TIME_RANGE_SECONDS[selected_time_range]

        safe_page = max(1, int(page or 1))
        safe_page_size = max(1, min(int(page_size or limit or 100), 100))
        offset = (safe_page - 1) * safe_page_size
        # Zabbix API problem.get has limit but no direct offset.
        # Fetch enough rows up to requested page, then slice in service layer.
        max_fetch_limit = 2000
        fetch_limit = min(offset + safe_page_size, max_fetch_limit)

        problems, total_count = await asyncio.gather(
            zabbix_client.get_problems(
                severity_min=severity_min,
                host_ids=host_ids,
                limit=fetch_limit,
                time_from=time_from,
            ),
            zabbix_client.get_problems_count(
                severity_min=severity_min,
                host_ids=host_ids,
                time_from=time_from,
            ),
        )

        paged_problems = problems[offset: offset + safe_page_size]

        trigger_ids = list({p.get("objectid") for p in paged_problems if p.get("objectid")})
        trigger_host_map: Dict[str, str] = {}
        if trigger_ids:
            try:
                triggers = await zabbix_client._call("trigger.get", {
                    "triggerids": trigger_ids,
                    "output": ["triggerid"],
                    "selectHosts": ["hostid", "name"],
                })
                for t in triggers:
                    hosts_list = t.get("hosts", [])
                    if hosts_list:
                        trigger_host_map[t["triggerid"]] = hosts_list[0].get("name", "")
            except Exception as e:
                logger.warning(f"[ZabbixMonitor] Failed to fetch trigger hosts: {e}")

        enriched = []
        bkk_tz = timezone(timedelta(hours=7))
        for p in paged_problems:
            sev = str(p.get("severity", "0"))
            meta = SEVERITY_MAP.get(sev, SEVERITY_MAP["0"])

            # Lookup host name via trigger mapping
            host_name = trigger_host_map.get(p.get("objectid", ""), "")

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
                "host": host_name,
                "severity": int(sev),
                "severity_label": meta["label"],
                "severity_color": meta["color"],
                "severity_emoji": meta["emoji"],
                "clock": clock_raw,
                "datetime": dt_str,
                "acknowledged": p.get("acknowledged") == "1",
                "tags": p.get("tags", []),
            })

        # Count by severity (based on fetched window, not only current page)
        severity_counts = {str(i): 0 for i in range(6)}
        for p in problems:
            sev = str(p.get("severity", "0"))
            severity_counts[sev] += 1

        total_pages = max(1, (total_count + safe_page_size - 1) // safe_page_size)

        return {
            "total": total_count,
            "returned": len(enriched),
            "fetched": len(problems),
            "page": safe_page,
            "page_size": safe_page_size,
            "total_pages": total_pages,
            "has_next": safe_page < total_pages,
            "has_prev": safe_page > 1,
            "is_partial_window": total_count > fetch_limit,
            "time_range": selected_time_range,
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

        # Show only concise and human-meaningful information.
        # Keep just two sections for UI simplicity.
        categories = {
            "system": [],
            "other": [],
        }

        system_keywords = [
            "sysname", "sysdescr", "syslocation", "syscontact",
            "hostname", "host name", "operating system", "os version",
            "software", "firmware", "serial", "model", "vendor",
        ]
        noisy_metric_keywords = [
            "ifinoctets", "ifoutoctets", "ifhcinoctets", "ifhcoutoctets",
            "net.if.in", "net.if.out", "bits received", "bits sent",
            "traffic", "throughput", "bandwidth", "packet", "discard", "error",
            "ifoperstatus", "ifadminstatus", "operational status", "admin status",
            "cpu", "processor", "load", "memory", "swap", "buffer",
            "disk", "storage", "filesystem", "uptime",
        ]
        numeric_like = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
        seen_keys = set()

        for item in snmp_items:
            key = item.get("key_", "").lower()
            name = item.get("name", "").lower()
            lastvalue = item.get("lastvalue", "").strip()

            # Skip items that have no data or are just master templates (like 'SNMP walk')
            if not lastvalue or "snmp walk" in name:
                continue

            # Drop highly volatile counters/metrics that change continuously.
            if numeric_like.match(lastvalue):
                continue

            # Skip obvious noisy metric/status lines.
            if any(k in key or k in name for k in noisy_metric_keywords):
                continue

            dedupe_id = f"{item.get('key_', '')}|{item.get('name', '')}".lower()
            if dedupe_id in seen_keys:
                continue
            seen_keys.add(dedupe_id)

            # Truncate extremely long values (like System Description) to keep UI clean
            if len(lastvalue) > 55:
                lastvalue = lastvalue[:52] + "..."

            formatted = {
                "itemid": item["itemid"],
                "name": item.get("name", ""),
                "key": item.get("key_", ""),
                "lastvalue": lastvalue,
                "units": item.get("units", ""),
                "lastclock": item.get("lastclock", ""),
            }

            if any(k in key or k in name for k in system_keywords):
                categories["system"].append(formatted)
            else:
                categories["other"].append(formatted)

        # Keep response compact.
        if categories.get("system"):
            categories["system"] = categories["system"][:20]
        if categories.get("other"):
            categories["other"] = categories["other"][:20]

        # Remove empty categories to keep UI clean
        categories = {k: v for k, v in categories.items() if len(v) > 0}
        
        # Return categories directly as the frontend maps over the root object
        self._cache_set(cache_key, categories, ttl_seconds=20)
        return categories


    # ── Top Metrics Dashboard ──────────────────────────────────────

    async def get_top_metrics(
        self,
        limit: int = 5,
        mode: str = "current",
        window_hours: int = 1,
    ) -> Dict[str, Any]:
        """
        วิเคราะห์และดึงค่า Top N (Bandwidth, CPU, Memory)
        ใช้ Zabbix Tag-based filtering (component: cpu / memory / network)
        กรองเฉพาะ hosts ที่ online (available) เท่านั้น เพื่อแสดงข้อมูล real-time
        """
        selected_mode = (mode or "current").strip().lower()
        if selected_mode not in {"current", "peak"}:
            selected_mode = "current"
        lookback_hours = max(1, int(window_hours or 1))

        cache_key = f"top_metrics:{limit}:{selected_mode}:{lookback_hours}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # 1. Get all hosts แล้วกรองเฉพาะ enabled + online (available)
        hosts = await self.get_all_hosts()
        online_hosts = [
            h for h in hosts
            if h["status"] == "enabled" and h["availability"] == "available"
        ]
        host_ids = [h["hostid"] for h in online_hosts]
        host_map = {h["hostid"]: h["hostname"] for h in online_hosts}

        total_enabled = sum(1 for h in hosts if h["status"] == "enabled")

        if not host_ids:
            return {
                "top_cpu": [],
                "top_memory": [],
                "top_bandwidth": [],
                "_meta": {
                    "online_hosts": 0,
                    "total_enabled_hosts": total_enabled,
                    "timestamp": int(time.time()),
                    "note": "ไม่มี host ที่ online อยู่ในขณะนี้",
                },
            }

        # 2. Fetch items by tag (parallel) — ใช้ tag "component" ที่ Zabbix Template กำหนดไว้
        cpu_items, memory_items, network_items = await asyncio.gather(
            zabbix_client.get_items_by_tag(host_ids, tag="component", value="cpu"),
            zabbix_client.get_items_by_tag(host_ids, tag="component", value="memory"),
            zabbix_client.get_items_by_tag(host_ids, tag="component", value="network"),
        )

        logger.info(
            f"[ZabbixMonitor] Tag-based items (raw) — "
            f"CPU: {len(cpu_items)}, Memory: {len(memory_items)}, Network: {len(network_items)}"
        )

        # ── 2b. Filter stale items (lastclock > 10 minutes ago) ──
        # Hosts ที่ปิดอยู่จะยังมี lastvalue เก่าค้าง — ต้องตัดออก
        MAX_STALE_SECONDS = 600  # 10 นาที
        now = int(time.time())

        def _is_fresh(item: Dict[str, Any]) -> bool:
            """ตรวจว่า item ถูก poll ภายใน 10 นาทีที่ผ่านมาหรือไม่"""
            try:
                lastclock = int(item.get("lastclock", "0"))
            except (ValueError, TypeError):
                return False
            return (now - lastclock) <= MAX_STALE_SECONDS

        cpu_items = [i for i in cpu_items if _is_fresh(i)]
        memory_items = [i for i in memory_items if _is_fresh(i)]
        network_items = [i for i in network_items if _is_fresh(i)]

        logger.info(
            f"[ZabbixMonitor] Tag-based items (fresh, ≤{MAX_STALE_SECONDS}s) — "
            f"CPU: {len(cpu_items)}, Memory: {len(memory_items)}, Network: {len(network_items)}"
        )

        host_interface_name_map: Dict[str, Dict[str, str]] = {}
        try:
            host_items_tasks = [zabbix_client.get_items(host_id=hid, limit=2000) for hid in host_ids]
            host_items_results = await asyncio.gather(*host_items_tasks)
            for hid, items in zip(host_ids, host_items_results):
                host_interface_name_map[str(hid)] = self._build_interface_name_map_from_items(items)
        except Exception as e:
            logger.warning(f"[ZabbixMonitor] Failed to build interface name map: {e}")

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
        # mode=current: rank by latest value
        # mode=peak:    rank by peak Total (In+Out per timestamp) in lookback window
        traffic_items = [i for i in network_items if self._is_traffic_item(i)]

        history_by_item: Dict[str, Dict[int, float]] = {}
        if selected_mode == "peak":
            time_from_bw = now - (lookback_hours * 3600)
            traffic_item_ids = [str(i.get("itemid")) for i in traffic_items if i.get("itemid")]

            if traffic_item_ids:
                history_float, history_uint = await asyncio.gather(
                    zabbix_client.get_history(
                        item_ids=traffic_item_ids,
                        history_type=0,
                        time_from=time_from_bw,
                        limit=20000,
                        sort_order="ASC",
                    ),
                    zabbix_client.get_history(
                        item_ids=traffic_item_ids,
                        history_type=3,
                        time_from=time_from_bw,
                        limit=20000,
                        sort_order="ASC",
                    ),
                )

                for h in history_float + history_uint:
                    iid = str(h.get("itemid", ""))
                    if not iid:
                        continue
                    try:
                        clock = int(h.get("clock", 0))
                        value_bps = float(h.get("value", "0") or 0)
                    except (TypeError, ValueError):
                        continue
                    if clock <= 0 or value_bps < 0:
                        continue
                    bucket = history_by_item.setdefault(iid, {})
                    bucket[clock] = max(bucket.get(clock, 0.0), value_bps)

        traffic_by_interface: Dict[str, Dict[str, Any]] = {}
        for item in traffic_items:
            hostid = item.get("hostid")
            if not hostid:
                continue

            hostname = host_map.get(str(hostid), f"Host {hostid}")
            interface_name = self._extract_interface_name(item, host_interface_name_map.get(str(hostid), {}))
            if not interface_name:
                continue
            direction = self._detect_traffic_direction(item)

            aggregate_key = f"{hostid}|{interface_name}"
            if aggregate_key not in traffic_by_interface:
                traffic_by_interface[aggregate_key] = {
                    "host": hostname,
                    "host_id": str(hostid),
                    "interface": interface_name,
                    "in_by_clock": {},
                    "out_by_clock": {},
                }

            target = traffic_by_interface[aggregate_key]["in_by_clock" if direction == "Inbound" else "out_by_clock"]
            iid = str(item.get("itemid", ""))
            if selected_mode == "peak":
                item_history = history_by_item.get(iid, {})

                if item_history:
                    for clock, v in item_history.items():
                        target[clock] = max(target.get(clock, 0.0), v)
                else:
                    # Fallback when no history in lookback window: use latest sample.
                    try:
                        lv = float(item.get("lastvalue", "0") or 0)
                    except ValueError:
                        lv = 0.0
                    target[now] = max(target.get(now, 0.0), lv)
            else:
                try:
                    lv = float(item.get("lastvalue", "0") or 0)
                except ValueError:
                    lv = 0.0
                target[now] = max(target.get(now, 0.0), lv)

        top_traffic: List[Dict[str, Any]] = []
        for agg in traffic_by_interface.values():
            in_by_clock = agg["in_by_clock"]
            out_by_clock = agg["out_by_clock"]

            in_peak = max(in_by_clock.values()) if in_by_clock else 0.0
            out_peak = max(out_by_clock.values()) if out_by_clock else 0.0

            all_clocks = set(in_by_clock.keys()) | set(out_by_clock.keys())
            total_peak = max((in_by_clock.get(c, 0.0) + out_by_clock.get(c, 0.0)) for c in all_clocks) if all_clocks else 0.0
            if total_peak <= 0:
                continue

            total_fmt = self._format_bps(total_peak)
            in_fmt = self._format_bps(in_peak)
            out_fmt = self._format_bps(out_peak)

            top_traffic.append({
                "host": agg["host"],
                "host_id": agg["host_id"],
                "interface": agg["interface"],
                "direction": "Total",
                "value_bps": round(total_peak, 0),
                "value": total_fmt["value"],
                "unit": total_fmt["unit"],
                "in_value": in_fmt["value"],
                "in_unit": in_fmt["unit"],
                "out_value": out_fmt["value"],
                "out_unit": out_fmt["unit"],
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

        # ── 5. คำนวณ data freshness จาก lastclock ──────────────
        # หาค่า lastclock ล่าสุดจาก items ทั้งหมดเพื่อบอก Frontend ว่าข้อมูล fresh แค่ไหน
        now = int(time.time())
        all_lastclocks = []
        for items_list in [cpu_items, memory_items, network_items]:
            for item in items_list:
                lc = item.get("lastclock", "0")
                try:
                    lc_int = int(lc) if lc else 0
                    if lc_int > 0:
                        all_lastclocks.append(lc_int)
                except ValueError:
                    pass

        newest_data = max(all_lastclocks) if all_lastclocks else 0
        oldest_data = min(all_lastclocks) if all_lastclocks else 0
        data_age_seconds = (now - newest_data) if newest_data else None

        result = {
            "top_cpu": top_cpu_dedup,
            "top_memory": top_mem_dedup,
            "top_bandwidth": top_traffic,
            "_meta": {
                "online_hosts": len(online_hosts),
                "total_enabled_hosts": total_enabled,
                "timestamp": now,
                "newest_data_clock": newest_data,
                "data_age_seconds": data_age_seconds,
                "cache_ttl_seconds": 15,
                "top_bandwidth_basis": (
                    f"peak_total_bps_last_{lookback_hours}h"
                    if selected_mode == "peak"
                    else "current_total_bps_latest"
                ),
                "top_bandwidth_mode": selected_mode,
                "top_bandwidth_window_hours": lookback_hours,
                "note": "แสดงเฉพาะอุปกรณ์ที่ online (available) เท่านั้น",
            },
        }

        self._cache_set(cache_key, result, ttl_seconds=15)
        return result


# ── Singleton ────────────────────────────────────────────────────
zabbix_monitoring_service = ZabbixMonitoringService()
