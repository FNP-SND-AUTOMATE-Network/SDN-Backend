"""
Interface Normalizer
Convert vendor-specific response to Unified format

Enhanced mappings for Driver Factory Pattern:
- Huawei: ipv4Config/am4CfgAddrs/ifIpAddr -> Unified ip
- Cisco: ietf-ip:ipv4/address[0]/ip -> Unified ip
- Status: shutdown/adminStatus -> enabled: boolean
"""
from typing import Any, Dict, List, Optional
from app.schemas.unified import UnifiedInterfaceStatus, UnifiedInterfaceList, InterfaceConfig


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
    
    # ===== New Static Methods for Driver Factory Pattern =====
    
    @staticmethod
    def to_interface_config(vendor: str, raw: Dict[str, Any]) -> InterfaceConfig:
        """
        Convert vendor-specific JSON response to Unified InterfaceConfig
        
        Mappings:
        - Huawei: ipv4Config/am4CfgAddrs/am4CfgAddr[0]/ifIpAddr -> ip
        - Cisco: ietf-ip:ipv4/address[0]/ip -> ip
        - Status: shutdown(Cisco)/adminStatus(Huawei) -> enabled: boolean
        
        Args:
            vendor: Vendor name ("cisco", "huawei")
            raw: Raw JSON response from ODL
            
        Returns:
            InterfaceConfig with normalized values
        """
        vendor_lower = vendor.lower()
        
        if vendor_lower == "cisco":
            return InterfaceNormalizer._parse_cisco_to_config(raw)
        elif vendor_lower == "huawei":
            return InterfaceNormalizer._parse_huawei_to_config(raw)
        else:
            # Generic fallback - try to extract basic info
            return InterfaceConfig(
                name=raw.get("name", "unknown"),
                enabled=True
            )
    
    @staticmethod
    def _parse_cisco_to_config(raw: Dict[str, Any]) -> InterfaceConfig:
        """
        Parse Cisco IETF response to InterfaceConfig
        
        IETF structure:
        - name: interface name
        - enabled: boolean (no shutdown = True)
        - ietf-ip:ipv4/address[0]/ip: IP address
        - ietf-ip:ipv4/address[0]/netmask: subnet mask
        """
        iface = raw.get("ietf-interfaces:interface") or raw
        if isinstance(iface, list):
            iface = iface[0] if iface else {}
        
        name = iface.get("name", "")
        enabled = iface.get("enabled", True)
        description = iface.get("description")
        mtu = iface.get("mtu")
        
        # Extract IP from ietf-ip:ipv4
        ip: Optional[str] = None
        mask: Optional[str] = None
        ip_block = iface.get("ietf-ip:ipv4", {})
        addresses = ip_block.get("address", [])
        if addresses:
            first_addr = addresses[0]
            ip = first_addr.get("ip")
            # Try netmask first, then prefix-length
            mask = first_addr.get("netmask")
            if not mask and first_addr.get("prefix-length"):
                mask = str(first_addr.get("prefix-length"))
        
        return InterfaceConfig(
            name=name,
            ip=ip,
            mask=mask,
            enabled=enabled,
            description=description,
            mtu=mtu
        )
    
    @staticmethod
    def _parse_huawei_to_config(raw: Dict[str, Any]) -> InterfaceConfig:
        """
        Parse Huawei huawei-ifm response to InterfaceConfig
        
        VRP8 structure:
        - ifName: interface name
        - adminStatus: "up" | "down" -> enabled boolean
        - huawei-ip:ipv4Config/am4CfgAddrs/am4CfgAddr[0]/ifIpAddr: IP address
        - huawei-ip:ipv4Config/am4CfgAddrs/am4CfgAddr[0]/subnetMask: mask
        """
        iface = raw.get("huawei-ifm:interface") or raw
        if isinstance(iface, list):
            iface = iface[0] if iface else {}
        
        name = iface.get("ifName", "")
        admin_status = iface.get("adminStatus", "up")
        enabled = admin_status.lower() == "up"
        description = iface.get("description")
        mtu = iface.get("mtu")
        
        # Extract IP from huawei-ip:ipv4Config (VRP8 structure)
        ip: Optional[str] = None
        mask: Optional[str] = None
        ipv4_config = iface.get("huawei-ip:ipv4Config", {})
        am4_cfg_addrs = ipv4_config.get("am4CfgAddrs", {})
        am4_cfg_addr = am4_cfg_addrs.get("am4CfgAddr", [])
        if am4_cfg_addr:
            first_addr = am4_cfg_addr[0]
            ip = first_addr.get("ifIpAddr")
            mask = first_addr.get("subnetMask")
        
        return InterfaceConfig(
            name=name,
            ip=ip,
            mask=mask,
            enabled=enabled,
            description=description,
            mtu=mtu
        )

