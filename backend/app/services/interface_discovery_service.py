"""
Interface Discovery Service
ดึง interface list จาก device ผ่าน ODL แล้ว cache ไว้ใน memory
Merge ข้อมูลจาก Config (native) + Operational (interfaces-oper) ให้ครบใน API เดียว
"""
import time
from typing import Any, Dict, List, Optional
from app.clients.odl_restconf_client import OdlRestconfClient
from app.builders.odl_paths import odl_mount_base
from app.schemas.request_spec import RequestSpec
from app.core.logging import logger


# ===== In-memory TTL Cache =====
_cache: Dict[str, Dict[str, Any]] = {}
DEFAULT_TTL_SECONDS = 300  # 5 minutes


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
        Returns cached data if available and not expired.
        """
        # Check cache
        if not force_refresh:
            cached = self._get_cached(node_id)
            if cached is not None:
                logger.info(f"InterfaceDiscovery: cache hit for {node_id}")
                return cached

        # Fetch from device
        logger.info(f"InterfaceDiscovery: fetching interfaces from {node_id}")

        if vendor == "CISCO_IOS_XE":
            interfaces = await self._discover_cisco(node_id)
        elif vendor == "HUAWEI_VRP":
            interfaces = self._parse_huawei({})
        else:
            interfaces = await self._discover_cisco(node_id)

        # Cache result
        self._set_cache(node_id, interfaces)
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

    # ===== Huawei Parser (placeholder) =====

    def _parse_huawei(self, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Huawei interface response (placeholder for future)"""
        logger.warning("Huawei interface parsing not yet implemented")
        return []

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
