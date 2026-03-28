"""
Zabbix Monitoring Service
Business logic layer สำหรับดึงข้อมูล SNMP/monitoring จาก Zabbix API
แล้วจัดรูปแบบให้พร้อมใช้บน Frontend Dashboard

Flow:
  Frontend → REST API → ZabbixMonitoringService → ZabbixClient → Zabbix JSON-RPC API
"""

import asyncio
import time
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

    async def get_host_traffic(
        self,
        host_id: str,
        period_hours: int = 1,
        interface_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        ดึงข้อมูล traffic ของ interfaces (ifInOctets, ifOutOctets, ifSpeed, etc.)
        สำหรับแสดงกราฟ Traffic บน Dashboard

        Returns time-series data พร้อมค่า in/out bytes
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
                "message": "No traffic items found for this host",
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
            history_by_item[iid].append({
                "clock": int(h.get("clock", 0)),
                "value": h.get("value", "0"),
            })

        # Build interface traffic data
        interfaces_data = []
        for item in traffic_items:
            iid = item["itemid"]
            interfaces_data.append({
                "itemid": iid,
                "name": item.get("name", ""),
                "key": item.get("key_", ""),
                "units": item.get("units", ""),
                "lastvalue": item.get("lastvalue", ""),
                "history": history_by_item.get(iid, []),
            })

        result = {
            "host_id": host_id,
            "period_hours": period_hours,
            "time_from": time_from,
            "time_till": int(time.time()),
            "interfaces": interfaces_data,
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
        for p in problems:
            sev = str(p.get("severity", "0"))
            meta = SEVERITY_MAP.get(sev, SEVERITY_MAP["0"])
            enriched.append({
                "eventid": p.get("eventid"),
                "objectid": p.get("objectid"),
                "name": p.get("name", ""),
                "severity": int(sev),
                "severity_label": meta["label"],
                "severity_color": meta["color"],
                "severity_emoji": meta["emoji"],
                "clock": p.get("clock", ""),
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
            return {"top_cpu": [], "top_memory": [], "top_bandwidth": [], "top_uptime": []}

        # 2. Fetch all SNMP items for these hosts
        # Type 20 = Zabbix 6.0+, Type 4 = older
        items_v2 = await zabbix_client.get_items(host_ids=host_ids, item_type=4, limit=0)
        items_v3 = await zabbix_client.get_items(host_ids=host_ids, item_type=20, limit=0)
        all_items = items_v2 + items_v3

        top_cpu = []
        top_memory = []
        top_traffic = []
        top_uptime = []

        for item in all_items:
            hostid = item.get("hostid")
            if not hostid:
                continue
            
            hostname = host_map.get(str(hostid), f"Host {hostid}")
            key = item.get("key_", "").lower()
            name = item.get("name", "").lower()
            lastvalue = item.get("lastvalue", "0")
            
            try:
                val = float(lastvalue) if lastvalue else 0.0
            except ValueError:
                val = 0.0

            if val <= 0:
                continue

            # CPU filter (looks for 'cpu' or 'processor' and expects percentage)
            if any(k in key or k in name for k in ["cpu", "processor", "load"]) and "%" in item.get("units", "%"):
                # Avoid dupes per host, or just collect all? Let's collect all and we can deduplicate later if needed.
                # Usually we want the *highest* CPU core or average.
                top_cpu.append({"host": hostname, "name": item.get("name"), "value": round(val, 2), "unit": "%"})
                    
            # Memory filter
            elif any(k in key or k in name for k in ["memory utilization", "mem util", "pused"]):
                unit = item.get("units", "%")
                top_memory.append({"host": hostname, "name": item.get("name"), "value": round(val, 2), "unit": unit})

            # Traffic filter (convert bits or octets)
            elif any(k in key for k in ["ifinoctets", "ifoutoctets", "net.if.in", "net.if.out"]):
                if "octets" in key or "octets" in name:
                    # Octets = bytes -> bps
                    mbps = (val * 8) / 1_000_000
                else:
                    # Often bits directly if it's zabbix agent, but we are querying SNMP which is octets.
                    # ifHCInOctets, ifInOctets. Assume octets (bytes) -> bps.
                    mbps = (val * 8) / 1_000_000

                if mbps > 0.01:  # Only significant traffic
                    direction = "Inbound" if "in" in key.lower() else "Outbound"
                    # clean up interface name
                    interface_name = item.get("name").replace("Bits received", "").replace("Bits sent", "").replace("Interface", "").strip()
                    top_traffic.append({
                        "host": hostname, 
                        "interface": interface_name, 
                        "direction": direction,
                        "value": round(mbps, 2), 
                        "unit": "Mbps"
                    })

            # Uptime filter
            elif any(k in key or k in name for k in ["sysuptime", "uptime"]):
                if "sysuptime" in key or "sysuptime" in name.lower():
                    # Check if units is timeticks
                    if item.get("units") == "uptime":
                        # Zabbix uptime value is natively in seconds actually, or timeticks.
                        # Usually sysUpTime is in hundredths of a second (Timeticks)
                        days = round(val / 8640000, 1)
                    else:
                        days = round(val / 8640000, 1)
                else:
                    days = round(val / 86400, 1) # assuming seconds
                
                # Deduplicate uptime (hosts might have multiple, only keep one)
                if not any(u["host"] == hostname for u in top_uptime):
                    top_uptime.append({"host": hostname, "name": item.get("name"), "value": days, "unit": "Days"})

        # Group bandwidth by interface (IN + OUT)?? For simplicity, Top Traffic can just be top ports regardless of direction, or max of in/out.
        # Let's just sort and take top limit.
        top_traffic = sorted(top_traffic, key=lambda x: x["value"], reverse=True)[:limit]
        
        # Deduplicate CPU & Memory (take highest per host)
        top_cpu_dedup = []
        for c in sorted(top_cpu, key=lambda x: x["value"], reverse=True):
            if not any(x["host"] == c["host"] for x in top_cpu_dedup):
                top_cpu_dedup.append(c)
                if len(top_cpu_dedup) >= limit: break

        top_mem_dedup = []
        for m in sorted(top_memory, key=lambda x: x["value"], reverse=True):
            if not any(x["host"] == m["host"] for x in top_mem_dedup):
                top_mem_dedup.append(m)
                if len(top_mem_dedup) >= limit: break

        top_uptime = sorted(top_uptime, key=lambda x: x["value"])[:limit] # Lowest uptime first (recently rebooted)

        result = {
            "top_cpu": top_cpu_dedup,
            "top_memory": top_mem_dedup,
            "top_bandwidth": top_traffic,
            "top_uptime": top_uptime,
        }
        
        self._cache_set(cache_key, result, ttl_seconds=30)
        return result


# ── Singleton ────────────────────────────────────────────────────
zabbix_monitoring_service = ZabbixMonitoringService()
