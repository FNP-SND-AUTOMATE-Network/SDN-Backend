"""
Interface Discovery Service
ดึง interface list จาก device ผ่าน ODL แล้ว cache ไว้ใน memory
Merge ข้อมูลจาก Config (native) + Operational (interfaces-oper) ให้ครบใน API เดียว

Protection layers (จากนอกเข้าใน):
  1. TTL Cache          — ถ้า cache ยังไม่หมดอายุ return ทันที ไม่ยิง ODL เลย
  2. Request Coalescing — ถ้า fetch กำลังทำงานอยู่ request ใหม่ "รอ" แทนที่จะยิง ODL ซ้ำ
  3. ODL Readiness Gate — ตรวจ connection_status ก่อนยิง RPC ทุกครั้ง
  4. force_refresh Cooldown — จำกัดว่า force refresh ได้ไม่เกินทุก N วินาที
"""
import asyncio
import time
from typing import Any, Dict, List, Optional
from app.clients.odl_restconf_client import OdlRestconfClient
from app.builders.odl_paths import odl_mount_base
from app.schemas.request_spec import RequestSpec
from app.core.logging import logger

# Lazy import to avoid circular dependency with odl_mount_service
def _get_mount_service():
    from app.services.odl_mount_service import OdlMountService
    return OdlMountService()


# ===== Module-level shared state (ใช้ร่วมกันทุก instance ใน process) =====

# TTL Cache: { node_id: { "interfaces": [...], "fetched_at": float } }
_cache: Dict[str, Dict[str, Any]] = {}
DEFAULT_TTL_SECONDS = 300  # 5 minutes

# In-flight locks: { node_id: asyncio.Lock }
# ป้องกันไม่ให้มี ODL request ซ้ำพร้อมกันสำหรับ node เดียวกัน
_in_flight: Dict[str, asyncio.Lock] = {}

# force_refresh cooldown tracking: { node_id: last_force_refresh_timestamp }
_last_force_refresh: Dict[str, float] = {}
FORCE_REFRESH_COOLDOWN_SECONDS = 30  # force refresh ได้ไม่เกินทุก 30 วินาที


class InterfaceDiscoveryService:
    """
    Discover and cache available interfaces on network devices.
    Merges config + operational data for a complete view.

    Supports:
    - Cisco IOS-XE (native YANG model + interfaces-oper)
    - Huawei (future)
    """

    def __init__(self, ttl: int = DEFAULT_TTL_SECONDS):
        self.odl = OdlRestconfClient()
        self.ttl = ttl

    # ===== Public API =====

    async def discover(
        self,
        node_id: str,
        vendor: str = "cisco",
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get full interface list for a device (config + operational merged).

        Protection layers (ทำงานตามลำดับ):
          1. Cache check  — ถ้ายังไม่หมดอายุ return ทันที
          2. Cooldown     — force_refresh ถูกจำกัดทุก 30 วินาที
          3. Lock acquire — ถ้ามี fetch ค้างอยู่ให้รอผลนั้น (request coalescing)
          4. Cache check อีกครั้ง — อาจมี fetch เสร็จระหว่างรอ lock
          5. ODL gate    — ตรวจ connection_status ก่อนยิง RPC
          6. Fetch & cache
        """
        # ── Layer 1: Cache (fast path) ───────────────────────────────────────
        if not force_refresh:
            cached = self._get_cached(node_id)
            if cached is not None:
                logger.info(f"InterfaceDiscovery: cache hit for '{node_id}'")
                return cached

        # ── Layer 2: force_refresh cooldown ──────────────────────────────────
        if force_refresh:
            now = time.time()
            last = _last_force_refresh.get(node_id, 0.0)
            remaining = FORCE_REFRESH_COOLDOWN_SECONDS - (now - last)
            if remaining > 0:
                logger.warning(
                    f"InterfaceDiscovery: force_refresh for '{node_id}' throttled. "
                    f"Please wait {remaining:.0f}s before forcing a refresh."
                )
                # Return stale cache if available, otherwise proceed normally
                stale = _cache.get(node_id)
                if stale:
                    logger.info(f"InterfaceDiscovery: returning stale cache for '{node_id}' due to cooldown")
                    return stale["interfaces"]
                # No cache at all — allow the fetch to proceed (cold start)
                force_refresh = False

        # ── Layer 3: Request coalescing via per-node asyncio.Lock ─────────────
        # Only ONE coroutine may hold the lock per node_id.
        # Any other coroutine that arrives while a fetch is in-progress will
        # block here; when the lock is released it will hit Layer 4 (cache)
        # and return without touching ODL at all.
        if node_id not in _in_flight:
            _in_flight[node_id] = asyncio.Lock()
        lock = _in_flight[node_id]

        async with lock:
            # ── Layer 4: Double-checked cache (after acquiring lock) ──────────
            # The previous holder of the lock already fetched and cached the data.
            if not force_refresh:
                cached = self._get_cached(node_id)
                if cached is not None:
                    logger.info(
                        f"InterfaceDiscovery: cache hit for '{node_id}' "
                        "(after lock — coalesced with in-flight request)"
                    )
                    return cached

            # ── Layer 5: ODL Readiness Gate ───────────────────────────────────
            await self._assert_node_connected(node_id)

            # ── Layer 6: Fetch ────────────────────────────────────────────────
            logger.info(f"InterfaceDiscovery: fetching interfaces from '{node_id}'")

            vendor_upper = str(vendor).upper()
            if vendor_upper in ("HUAWEI_VRP", "HUAWEI"):
                interfaces = await self._discover_huawei(node_id)
            elif vendor_upper in (
                "CISCO_IOS_XE", "CISCO", "CISCO_IOS",
                "CISCO_NXOS", "CISCO_ASA", "CISCO_NEXUS", "CISCO_IOS_XR"
            ):
                interfaces = await self._discover_cisco(node_id)
            else:
                interfaces = await self._discover_cisco(node_id)

            # Cache + update force_refresh timestamp
            self._set_cache(node_id, interfaces)
            if force_refresh:
                _last_force_refresh[node_id] = time.time()

            return interfaces

    async def get_interface_names(
        self,
        node_id: str,
        vendor: str = "cisco",
        force_refresh: bool = False,
    ) -> List[str]:
        """Get only interface names (for dropdown)"""
        interfaces = await self.discover(node_id, vendor, force_refresh)
        return [iface["name"] for iface in interfaces]

    def invalidate(self, node_id: str) -> None:
        """Remove cached data for a device"""
        _cache.pop(node_id, None)
        logger.info(f"InterfaceDiscovery: invalidated cache for {node_id}")

    def invalidate_all(self) -> None:
        """Clear all cached data"""
        _cache.clear()
        logger.info("InterfaceDiscovery: cleared all cache")

    # ===== ODL Readiness Gate =====

    async def _assert_node_connected(self, node_id: str) -> None:
        """
        Raise NodeNotReadyError if ODL has not finished mounting the node.

        ODL connection states (operational datastore):
          - 'connecting'        → NETCONF hello / YANG download in progress
                                   DO NOT send any RPC — it stacks up and
                                   causes session teardown
          - 'connected'         → Safe to issue get-config / get-interfaces
          - 'unable-to-connect' → Auth failure or unreachable host
          - not mounted at all   → Must call /mount first
        """
        try:
            mount_svc = _get_mount_service()
            status = await mount_svc.get_connection_status(node_id)
        except Exception as e:
            # If we can't reach ODL at all, fail loudly
            raise RuntimeError(
                f"Cannot check ODL status for '{node_id}': {e}"
            ) from e

        conn = status.get("connection_status", "unknown")
        mounted = status.get("mounted", False)

        logger.info(
            f"InterfaceDiscovery: ODL readiness check for '{node_id}' → "
            f"mounted={mounted}, connection_status='{conn}'"
        )

        if not mounted:
            raise ValueError(
                f"Device '{node_id}' is not mounted in ODL. "
                "Please call POST /devices/{node_id}/mount first."
            )

        if conn == "connecting":
            raise ValueError(
                f"Device '{node_id}' is still initializing in ODL "
                f"(connection_status='connecting'). "
                "ODL is currently downloading and compiling YANG modules. "
                "This can take 30–120 seconds for Cisco ASR hardware. "
                "Please wait and retry, or poll GET /devices/{node_id}/status "
                "until connection_status becomes 'connected'."
            )

        if conn in ("unable-to-connect", "failed"):
            raise ValueError(
                f"ODL cannot connect to device '{node_id}' "
                f"(connection_status='{conn}'). "
                "Verify NETCONF credentials and device reachability, "
                "then unmount and remount the device."
            )

        if conn != "connected":
            # Unknown / unexpected status — refuse to continue
            raise ValueError(
                f"Device '{node_id}' has unexpected ODL status '{conn}'. "
                "Cannot safely fetch interfaces. "
                "Poll GET /devices/{node_id}/status for more details."
            )
        # conn == 'connected' — safe to proceed

    # ===== Cisco Discovery (Config + Oper merged) =====

    async def _discover_cisco(self, node_id: str) -> List[Dict[str, Any]]:
        """
        Fetch config + operational data and merge them.
        
        1. GET /Cisco-IOS-XE-native:native/interface        → config (IP, shutdown, OSPF)
        2. GET /Cisco-IOS-XE-interfaces-oper:interfaces      → oper (MAC, speed, duplex, oper-status)
        3. Merge by interface name
        """
        mount = odl_mount_base(node_id)

        # Fetch config data
        config_raw = await self._fetch_config(mount)
        config_interfaces = self._parse_cisco_config(config_raw)

        # Fetch operational data
        try:
            oper_raw = await self._fetch_oper(mount)
            oper_map = self._parse_cisco_oper(oper_raw)
        except Exception as e:
            logger.warning(f"InterfaceDiscovery: oper fetch failed: {e}, using config only")
            oper_map = {}

        # Merge: config เป็นหลัก, เพิ่ม oper fields เข้าไป
        for iface in config_interfaces:
            oper_data = oper_map.get(iface["name"], {})
            iface["oper_status"] = oper_data.get("oper_status")
            iface["mac_address"] = oper_data.get("mac_address")
            iface["speed"] = oper_data.get("speed")
            iface["duplex"] = oper_data.get("duplex")
            iface["auto_negotiate"] = oper_data.get("auto_negotiate")
            iface["media_type"] = oper_data.get("media_type")
            iface["last_change"] = oper_data.get("last_change")

        return config_interfaces

    # ===== ODL Fetch Methods =====

    async def _fetch_config(self, mount: str) -> Dict[str, Any]:
        """GET config: /Cisco-IOS-XE-native:native/interface"""
        spec = RequestSpec(
            method="GET",
            datastore="config",
            path=f"{mount}/Cisco-IOS-XE-native:native/interface",
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent="discovery.interfaces.config",
            driver="interface_discovery",
        )
        return await self.odl.send(spec)

    async def _fetch_oper(self, mount: str) -> Dict[str, Any]:
        """GET operational: /Cisco-IOS-XE-interfaces-oper:interfaces"""
        spec = RequestSpec(
            method="GET",
            datastore="operational",
            path=f"{mount}/Cisco-IOS-XE-interfaces-oper:interfaces",
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent="discovery.interfaces.oper",
            driver="interface_discovery",
        )
        return await self.odl.send(spec)

    # ===== Cisco Config Parser =====

    def _parse_cisco_config(self, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Cisco native config response (grouped by type)"""
        interfaces_data = raw.get("Cisco-IOS-XE-native:interface", {})
        result = []

        for iface_type, iface_entries in interfaces_data.items():
            if isinstance(iface_entries, dict):
                iface_entries = [iface_entries]
            elif not isinstance(iface_entries, list):
                continue

            for entry in iface_entries:
                parsed = self._parse_config_entry(iface_type, entry)
                result.append(parsed)

        # Sort by type priority
        type_order = {
            "GigabitEthernet": 0, "TenGigabitEthernet": 1,
            "Loopback": 2, "Vlan": 3, "Tunnel": 4, "Port-channel": 5,
        }
        result.sort(key=lambda x: (type_order.get(x["type"], 99), x["number"]))
        return result

    def _parse_config_entry(self, iface_type: str, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a single config interface entry"""
        iface_num = str(entry.get("name", ""))
        full_name = f"{iface_type}{iface_num}"

        # Admin status
        admin_status = "down" if "shutdown" in entry else "up"

        # IPv4
        ipv4 = None
        ipv4_address = None
        subnet_mask = None
        ip_block = entry.get("ip", {})
        address_block = ip_block.get("address", {})
        primary = address_block.get("primary", {})
        if primary:
            ipv4_address = primary.get("address")
            subnet_mask = primary.get("mask")
            if ipv4_address and subnet_mask:
                ipv4 = f"{ipv4_address} ({subnet_mask})"

        # IPv6
        ipv6 = None
        ipv6_block = entry.get("ipv6", {})
        ipv6_addr_block = ipv6_block.get("address", {})
        prefix_list = ipv6_addr_block.get("prefix-list", [])
        if prefix_list and isinstance(prefix_list, list) and len(prefix_list) > 0:
            ipv6 = prefix_list[0].get("prefix")

        # OSPF detail
        ospf_block = (
            ip_block.get("Cisco-IOS-XE-ospf:router-ospf")
            or ip_block.get("router-ospf")
        )
        has_ospf = bool(ospf_block)
        ospf = None
        if ospf_block:
            ospf = self._parse_ospf_detail(ospf_block)

        # MTU
        mtu = ip_block.get("mtu") or entry.get("mtu")

        return {
            "name": full_name,
            "type": iface_type,
            "number": iface_num,
            "description": entry.get("description"),
            "admin_status": admin_status,
            "ipv4": ipv4,
            "ipv4_address": ipv4_address,
            "subnet_mask": subnet_mask,
            "ipv6": ipv6,
            "mtu": mtu,
            "has_ospf": has_ospf,
            "ospf": ospf,
            # Oper fields — will be merged from operational data
            "oper_status": None,
            "mac_address": None,
            "speed": None,
            "duplex": None,
            "auto_negotiate": None,
            "media_type": None,
            "last_change": None,
        }

    def _parse_ospf_detail(self, ospf_block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse OSPF detail from config.
        Structure:
        ospf: {
            process-id: [
                { id: 1, area: [{ area-id: 0 }] }
            ]
        }
        """
        try:
            ospf_data = ospf_block.get("ospf", {})
            process_list = ospf_data.get("process-id", [])
            
            if isinstance(process_list, dict):
                process_list = [process_list]
                
            if not process_list:
                return None
                
            # Take the first process
            process = process_list[0]
            process_id = process.get("id")
            
            # Get area
            area_list = process.get("area", [])
            if isinstance(area_list, dict):
                area_list = [area_list]
                
            area_id = None
            if area_list:
                area_id = area_list[0].get("area-id")
                
            return {
                "process_id": process_id,
                "area": area_id
            }
        except Exception as e:
            logger.warning(f"InterfaceDiscovery: failed to parse OSPF detail: {e}")
            return None

    # ===== Cisco Oper Parser =====

    def _parse_cisco_oper(self, raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Parse Cisco interfaces-oper response into a lookup map.
        Returns: { "GigabitEthernet3": { oper fields... }, ... }
        """
        oper_map = {}
        interfaces = raw.get("Cisco-IOS-XE-interfaces-oper:interfaces", {})
        iface_list = interfaces.get("interface", [])

        if isinstance(iface_list, dict):
            iface_list = [iface_list]

        for entry in iface_list:
            name = entry.get("name", "")
            if not name:
                continue

            # Oper status
            raw_oper = entry.get("oper-status", "")
            if "ready" in raw_oper or "up" in raw_oper:
                oper_status = "up"
            else:
                oper_status = "down"

            # Speed: "1000000000" → "1 Gbps"
            speed = self._format_speed(entry.get("speed"))

            # Duplex & auto-negotiate from ether-state
            ether_state = entry.get("ether-state", {})
            duplex = self._format_duplex(ether_state.get("negotiated-duplex-mode"))
            auto_negotiate = ether_state.get("auto-negotiate")
            media_type = self._format_media_type(ether_state.get("media-type"))

            oper_map[name] = {
                "oper_status": oper_status,
                "mac_address": entry.get("phys-address"),
                "speed": speed,
                "duplex": duplex,
                "auto_negotiate": auto_negotiate,
                "media_type": media_type,
                "last_change": entry.get("last-change"),
            }

        return oper_map

    # ===== Formatting Helpers =====

    @staticmethod
    def _format_speed(speed_str: Optional[str]) -> Optional[str]:
        """Convert speed string to human readable format"""
        if not speed_str:
            return None
        try:
            speed = int(speed_str)
            if speed >= 1_000_000_000:
                return f"{speed // 1_000_000_000} Gbps"
            elif speed >= 1_000_000:
                return f"{speed // 1_000_000} Mbps"
            elif speed >= 1_000:
                return f"{speed // 1_000} Kbps"
            return f"{speed} bps"
        except (ValueError, TypeError):
            return speed_str

    @staticmethod
    def _format_duplex(duplex_str: Optional[str]) -> Optional[str]:
        """Convert duplex mode to clean format"""
        if not duplex_str:
            return None
        mapping = {
            "full-duplex": "Full Duplex",
            "half-duplex": "Half Duplex",
            "auto": "Auto",
        }
        return mapping.get(duplex_str, duplex_str)

    @staticmethod
    def _format_media_type(media_str: Optional[str]) -> Optional[str]:
        """Convert media type to clean format"""
        if not media_str:
            return None
        mapping = {
            "ether-media-type-virtual": "Virtual",
            "ether-media-type-rj45": "RJ45",
            "ether-media-type-sfp": "SFP",
        }
        return mapping.get(media_str, media_str)

    async def _discover_huawei(self, node_id: str) -> List[Dict[str, Any]]:
        """
        Fetch Huawei VRP8 interfaces. ODL usually returns merged operational + config
        state for Huawei interfaces if requested without content filter, or we just
        fetch operational datastore which contains both.
        """
        mount = odl_mount_base(node_id)
        
        # Fetch interface list from operational datastore (contains status + config)
        try:
            raw = await self._fetch_huawei_interfaces(mount)
            return self._parse_huawei(raw)
        except Exception as e:
            logger.error(f"InterfaceDiscovery: Huawei fetch failed: {e}")
            return []

    async def _fetch_huawei_interfaces(self, mount: str) -> Dict[str, Any]:
        """GET Huawei interfaces: /huawei-ifm:ifm/interfaces"""
        spec = RequestSpec(
            method="GET",
            datastore="operational",
            path=f"{mount}/huawei-ifm:ifm/interfaces",
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent="discovery.interfaces.huawei",
            driver="interface_discovery",
        )
        return await self.odl.send(spec)

    def _parse_huawei(self, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Huawei interface response"""
        result = []
        ifm = raw.get("huawei-ifm:interfaces", {}) or raw.get("interfaces", {})
        iface_list = ifm.get("interface", [])
        
        if isinstance(iface_list, dict):
            iface_list = [iface_list]
            
        for entry in iface_list:
            ifname = entry.get("ifName", "")
            if not ifname:
                continue
                
            admin_status = entry.get("ifAdminStatus", "down")
            # Huawei huawei-ifm YANG model often omits ifOperStatus via ODL
            # Fallback to ifAdminStatus when ifOperStatus is not available
            oper_status = entry.get("ifOperStatus") or admin_status
            
            # Extract IPv4
            ipv4 = None
            ipv4_address = None
            subnet_mask = None
            ipv4_config = entry.get("huawei-ip:ipv4Config", {}) or entry.get("ipv4Config", {})
            am4_addrs = ipv4_config.get("am4CfgAddrs", {}).get("am4CfgAddr", [])
            if isinstance(am4_addrs, dict):
                am4_addrs = [am4_addrs]
                
            if am4_addrs:
                # Take the main address
                main_addr = next((addr for addr in am4_addrs if addr.get("addrType") == "main"), am4_addrs[0])
                ipv4_address = main_addr.get("ifIpAddr")
                subnet_mask = main_addr.get("subnetMask")
                if ipv4_address and subnet_mask:
                    ipv4 = f"{ipv4_address} ({subnet_mask})"
            
            # Extract IPv6
            ipv6 = None
            ipv6_config = entry.get("huawei-ip:ipv6Config", {}) or entry.get("ipv6Config", {})
            am6_addrs = ipv6_config.get("am6CfgAddrs", {}).get("am6CfgAddr", [])
            if isinstance(am6_addrs, dict):
                am6_addrs = [am6_addrs]
                
            if am6_addrs:
                main_v6 = next((addr for addr in am6_addrs if addr.get("addrType6") == "global"), am6_addrs[0])
                v6_addr = main_v6.get("ifIp6Addr")
                v6_len = main_v6.get("addrPrefixLen") or main_v6.get("ifIp6AddrPrefixLen")
                if v6_addr:
                    ipv6 = f"{v6_addr}/{v6_len}" if v6_len else v6_addr
            
            result.append({
                "name": ifname,
                "type": entry.get("ifType", "unknown"),
                "number": entry.get("ifNumber", "0"),
                "description": entry.get("ifDescr"),
                "admin_status": admin_status.lower(),
                "oper_status": oper_status.lower(),
                "ipv4": ipv4,
                "ipv4_address": ipv4_address,
                "subnet_mask": subnet_mask,
                "ipv6": ipv6,
                "mtu": entry.get("ifMtu"),
                "has_ospf": False, # OSPF discovery can be added later
                "ospf": None,
                "mac_address": entry.get("ifMac"),
                "speed": self._format_speed(entry.get("ifSpeed")),
                "duplex": self._format_duplex(entry.get("ifDuplex")),
            })
            
        # Sort interfaces
        result.sort(key=lambda x: x["name"])
        return result

    # ===== Cache Helpers =====

    def _get_cached(self, node_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get cached interfaces if not expired"""
        entry = _cache.get(node_id)
        if entry is None:
            return None

        elapsed = time.time() - entry["fetched_at"]
        if elapsed > self.ttl:
            logger.info(f"InterfaceDiscovery: cache expired for {node_id}")
            _cache.pop(node_id, None)
            return None

        return entry["interfaces"]

    def _set_cache(self, node_id: str, interfaces: List[Dict[str, Any]]) -> None:
        """Store interfaces in cache"""
        _cache[node_id] = {
            "interfaces": interfaces,
            "fetched_at": time.time(),
        }
        logger.info(
            f"InterfaceDiscovery: cached {len(interfaces)} interfaces for {node_id}"
        )
