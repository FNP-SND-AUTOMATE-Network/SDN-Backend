"""
Interface Normalizer
แปลง vendor-specific response เป็น Unified format
"""
from typing import Any, Dict, List
from app.schemas.unified import UnifiedInterfaceStatus, UnifiedInterfaceList


class InterfaceNormalizer:
    """
    Normalize interface responses from different vendors to unified format
    """
    
    def normalize_show_interface(self, driver_used: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize single interface response"""
        if driver_used == "openconfig":
            return self._normalize_openconfig_interface(raw)
        
        if driver_used == "cisco":
            return self._normalize_cisco_interface(raw)
        
        if driver_used == "huawei":
            return self._normalize_huawei_interface(raw)

        return {"vendor": driver_used, "raw": raw}
    
    def normalize_show_interfaces(self, driver_used: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize interface list response"""
        if driver_used == "openconfig":
            return self._normalize_openconfig_interfaces(raw)
        
        if driver_used == "cisco":
            return self._normalize_cisco_interfaces(raw)
        
        if driver_used == "huawei":
            return self._normalize_huawei_interfaces(raw)

        return {"vendor": driver_used, "raw": raw}
    
    # ===== OpenConfig Normalizers =====
    
    def _normalize_openconfig_interface(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize OpenConfig single interface"""
        iface = raw.get("openconfig-interfaces:interface") or raw
        
        # Handle list response (may contain single item)
        if isinstance(iface, list):
            iface = iface[0] if iface else {}
        
        name = iface.get("name") or iface.get("config", {}).get("name")
        state = iface.get("state", {})
        config = iface.get("config", {})
        
        # Extract IPv4 addresses
        ipv4 = []
        subifs = iface.get("subinterfaces", {}).get("subinterface", [])
        for sub in subifs:
            ipv4_block = sub.get("openconfig-if-ip:ipv4", {})
            for addr in ipv4_block.get("addresses", {}).get("address", []):
                ip = addr.get("ip") or addr.get("config", {}).get("ip")
                prefix = addr.get("config", {}).get("prefix-length")
                if ip and prefix:
                    ipv4.append(f"{ip}/{prefix}")
        
        # Extract IPv6 addresses
        ipv6 = []
        for sub in subifs:
            ipv6_block = sub.get("openconfig-if-ip:ipv6", {})
            for addr in ipv6_block.get("addresses", {}).get("address", []):
                ip = addr.get("ip") or addr.get("config", {}).get("ip")
                prefix = addr.get("config", {}).get("prefix-length")
                if ip and prefix:
                    ipv6.append(f"{ip}/{prefix}")
        
        # Extract counters
        counters = state.get("counters", {})
        
        out = UnifiedInterfaceStatus(
            name=name or "unknown",
            admin=str(state.get("admin-status", "")).lower() or None,
            oper=str(state.get("oper-status", "")).lower() or None,
            ipv4=ipv4,
            ipv6=ipv6,
            mac_address=state.get("mac-address"),
            mtu=config.get("mtu"),
            speed=state.get("speed"),
            description=config.get("description") or state.get("description"),
            last_change=state.get("last-change"),
            in_octets=counters.get("in-octets"),
            out_octets=counters.get("out-octets"),
            in_errors=counters.get("in-errors"),
            out_errors=counters.get("out-errors"),
            vendor="openconfig",
        )
        return out.model_dump()
    
    def _normalize_openconfig_interfaces(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize OpenConfig interface list"""
        interfaces_data = raw.get("openconfig-interfaces:interfaces", {})
        iface_list = interfaces_data.get("interface", [])
        
        interfaces = []
        up_count = 0
        down_count = 0
        
        for iface in iface_list:
            normalized = self._normalize_openconfig_interface({"openconfig-interfaces:interface": iface})
            interfaces.append(UnifiedInterfaceStatus(**normalized))
            
            if normalized.get("oper") == "up":
                up_count += 1
            else:
                down_count += 1
        
        out = UnifiedInterfaceList(
            interfaces=interfaces,
            total_count=len(interfaces),
            up_count=up_count,
            down_count=down_count
        )
        return out.model_dump()
    
    # ===== Cisco (IETF) Normalizers =====
    
    def _normalize_cisco_interface(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Cisco/IETF single interface"""
        iface = raw.get("ietf-interfaces:interface") or raw
        
        if isinstance(iface, list):
            iface = iface[0] if iface else {}
        
        name = iface.get("name", "unknown")
        enabled = iface.get("enabled")
        admin = "up" if enabled else "down"
        
        # Extract IPv4
        ipv4 = []
        ip_block = iface.get("ietf-ip:ipv4", {})
        for addr in (ip_block.get("address") or []):
            ip = addr.get("ip")
            mask = addr.get("netmask")
            prefix = addr.get("prefix-length")
            if ip:
                if prefix:
                    ipv4.append(f"{ip}/{prefix}")
                elif mask:
                    ipv4.append(f"{ip} ({mask})")
        
        # Extract IPv6
        ipv6 = []
        ipv6_block = iface.get("ietf-ip:ipv6", {})
        for addr in (ipv6_block.get("address") or []):
            ip = addr.get("ip")
            prefix = addr.get("prefix-length")
            if ip and prefix:
                ipv6.append(f"{ip}/{prefix}")
        
        # Statistics (if available)
        stats = iface.get("statistics", {})
        
        out = UnifiedInterfaceStatus(
            name=name,
            admin=admin,
            oper=iface.get("oper-status"),
            ipv4=ipv4,
            ipv6=ipv6,
            mac_address=iface.get("phys-address"),
            mtu=iface.get("mtu"),
            speed=iface.get("speed"),
            description=iface.get("description"),
            last_change=iface.get("last-change"),
            in_octets=stats.get("in-octets"),
            out_octets=stats.get("out-octets"),
            in_errors=stats.get("in-errors"),
            out_errors=stats.get("out-errors"),
            vendor="cisco",
        )
        return out.model_dump()
    
    def _normalize_cisco_interfaces(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Cisco/IETF interface list"""
        interfaces_data = raw.get("ietf-interfaces:interfaces", {})
        iface_list = interfaces_data.get("interface", [])
        
        interfaces = []
        up_count = 0
        down_count = 0
        
        for iface in iface_list:
            normalized = self._normalize_cisco_interface({"ietf-interfaces:interface": iface})
            interfaces.append(UnifiedInterfaceStatus(**normalized))
            
            if normalized.get("admin") == "up":
                up_count += 1
            else:
                down_count += 1
        
        out = UnifiedInterfaceList(
            interfaces=interfaces,
            total_count=len(interfaces),
            up_count=up_count,
            down_count=down_count
        )
        return out.model_dump()
    
    # ===== Huawei Normalizers =====
    
    def _normalize_huawei_interface(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Huawei single interface"""
        iface = raw.get("huawei-ifm:interface") or raw
        
        if isinstance(iface, list):
            iface = iface[0] if iface else {}
        
        name = iface.get("ifName", "unknown")
        admin = iface.get("adminStatus", "").lower()
        oper = iface.get("operStatus", "").lower()
        
        # Extract IPv4
        ipv4 = []
        ipv4_block = iface.get("ipv4", {})
        addresses = ipv4_block.get("addresses", {}).get("address", [])
        for addr in addresses:
            ip = addr.get("ip")
            mask = addr.get("mask")
            if ip and mask:
                ipv4.append(f"{ip} ({mask})")
        
        # Extract IPv6
        ipv6 = []
        ipv6_block = iface.get("ipv6", {})
        ipv6_addresses = ipv6_block.get("addresses", {}).get("address", [])
        for addr in ipv6_addresses:
            ip = addr.get("ip")
            prefix = addr.get("prefix-length")
            if ip and prefix:
                ipv6.append(f"{ip}/{prefix}")
        
        # Statistics
        stats = iface.get("statistics", {})
        
        out = UnifiedInterfaceStatus(
            name=name,
            admin=admin or None,
            oper=oper or None,
            ipv4=ipv4,
            ipv6=ipv6,
            mac_address=iface.get("macAddress"),
            mtu=iface.get("mtu"),
            speed=iface.get("ifSpeed"),
            description=iface.get("description") or iface.get("descr"),
            in_octets=stats.get("inOctets"),
            out_octets=stats.get("outOctets"),
            in_errors=stats.get("inErrors"),
            out_errors=stats.get("outErrors"),
            vendor="huawei",
        )
        return out.model_dump()
    
    def _normalize_huawei_interfaces(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Huawei interface list"""
        interfaces_data = raw.get("huawei-ifm:interfaces", {})
        iface_list = interfaces_data.get("interface", [])
        
        interfaces = []
        up_count = 0
        down_count = 0
        
        for iface in iface_list:
            normalized = self._normalize_huawei_interface({"huawei-ifm:interface": iface})
            interfaces.append(UnifiedInterfaceStatus(**normalized))
            
            if normalized.get("oper") == "up":
                up_count += 1
            else:
                down_count += 1
        
        out = UnifiedInterfaceList(
            interfaces=interfaces,
            total_count=len(interfaces),
            up_count=up_count,
            down_count=down_count
        )
        return out.model_dump()
