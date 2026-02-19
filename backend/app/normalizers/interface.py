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
        if driver_used == "cisco" or driver_used == "IOS_XE":
            return self._normalize_cisco_interface(raw)
        
        if driver_used == "huawei" or driver_used == "HUAWEI_VRP":
            return self._normalize_huawei_interface(raw)

        return {"vendor": driver_used, "raw": raw}
    
    def normalize_show_interfaces(self, driver_used: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize interface list response"""
        if driver_used == "cisco" or driver_used == "IOS_XE":
            return self._normalize_cisco_interfaces(raw)
        
        if driver_used == "huawei" or driver_used == "HUAWEI_VRP":
            return self._normalize_huawei_interfaces(raw)

        return {"vendor": driver_used, "raw": raw}
    
    
    # ===== Cisco (Native IOS-XE) Normalizers =====
    
    @staticmethod
    def _parse_native_single(iface_type: str, iface: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a single native IOS-XE interface entry into normalized fields.
        
        Native response structure:
        - name: interface number (e.g. "2")
        - shutdown: [null] means admin down, absence means admin up
        - ip.address.primary.address + mask: IPv4
        - ipv6.address.prefix-list: IPv6
        """
        # Build full name: Type + Number (e.g. "GigabitEthernet" + "2")
        iface_num = str(iface.get("name", ""))
        full_name = f"{iface_type}{iface_num}"
        
        # Admin status: shutdown leaf present = down
        has_shutdown = "shutdown" in iface
        admin = "down" if has_shutdown else "up"
        
        # Extract IPv4 from ip.address.primary
        ipv4 = []
        ip_block = iface.get("ip", {})
        address_block = ip_block.get("address", {})
        primary = address_block.get("primary", {})
        if primary:
            ip = primary.get("address")
            mask = primary.get("mask")
            if ip and mask:
                ipv4.append(f"{ip} ({mask})")
        # Also check secondary addresses
        secondary_list = address_block.get("secondary", [])
        if isinstance(secondary_list, dict):
            secondary_list = [secondary_list]
        for sec in secondary_list:
            ip = sec.get("address")
            mask = sec.get("mask")
            if ip and mask:
                ipv4.append(f"{ip} ({mask}) secondary")
        
        # Extract IPv6 from ipv6.address.prefix-list
        ipv6 = []
        ipv6_block = iface.get("ipv6", {})
        ipv6_addr_block = ipv6_block.get("address", {})
        prefix_list = ipv6_addr_block.get("prefix-list", [])
        if isinstance(prefix_list, dict):
            prefix_list = [prefix_list]
        for entry in prefix_list:
            prefix = entry.get("prefix")
            if prefix:
                ipv6.append(prefix)
        
        return {
            "name": full_name,
            "admin": admin,
            "ipv4": ipv4,
            "ipv6": ipv6,
            "mtu": ip_block.get("mtu") or iface.get("mtu"),
            "description": iface.get("description"),
        }
    
    def _normalize_cisco_interface(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Cisco IOS-XE Native single interface response.
        
        Response format from ODL:
        { "Cisco-IOS-XE-native:GigabitEthernet": [{ "name": "2", ... }] }
        or { "Cisco-IOS-XE-native:GigabitEthernet": { "name": "2", ... } }  (single item quirk)
        """
        # Find the interface type key in the response
        for key, value in raw.items():
            if key.startswith("Cisco-IOS-XE-native:"):
                iface_type = key.replace("Cisco-IOS-XE-native:", "")
                # Handle ODL quirk: single item = dict, multiple = list
                if isinstance(value, dict):
                    iface = value
                elif isinstance(value, list) and value:
                    iface = value[0]
                else:
                    continue
                
                parsed = self._parse_native_single(iface_type, iface)
                out = UnifiedInterfaceStatus(
                    name=parsed["name"],
                    admin=parsed["admin"],
                    oper=None,
                    ipv4=parsed["ipv4"],
                    ipv6=parsed["ipv6"],
                    mtu=parsed["mtu"],
                    description=parsed["description"],
                    vendor="cisco",
                )
                return out.model_dump()
        
        # Fallback
        return UnifiedInterfaceStatus(name="unknown", vendor="cisco").model_dump()
    
    def _normalize_cisco_interfaces(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Cisco IOS-XE Native interface list response.
        
        Response is grouped by type:
        {
            "Cisco-IOS-XE-native:interface": {
                "GigabitEthernet": [{ "name": "1" }, { "name": "2" }],
                "Loopback": [{ "name": "0" }]
            }
        }
        
        Handles ODL quirk: single interface returns dict instead of list.
        """
        interfaces_data = raw.get("Cisco-IOS-XE-native:interface", {})
        
        interfaces = []
        up_count = 0
        down_count = 0
        
        # Iterate through all interface types (GigabitEthernet, Loopback, etc.)
        for iface_type, iface_entries in interfaces_data.items():
            # Handle ODL quirk: single item = dict, multiple = list
            if isinstance(iface_entries, dict):
                iface_entries = [iface_entries]
            elif not isinstance(iface_entries, list):
                continue
            
            for iface in iface_entries:
                parsed = self._parse_native_single(iface_type, iface)
                status = UnifiedInterfaceStatus(
                    name=parsed["name"],
                    admin=parsed["admin"],
                    oper=None,
                    ipv4=parsed["ipv4"],
                    ipv6=parsed["ipv6"],
                    mtu=parsed["mtu"],
                    description=parsed["description"],
                    vendor="cisco",
                )
                interfaces.append(status)
                
                if parsed["admin"] == "up":
                    up_count += 1
                else:
                    down_count += 1
        
        # Sort by name alphabetically
        interfaces.sort(key=lambda x: x.name)
        
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
        
        if vendor_lower == "cisco" or vendor == "IOS_XE":
            return InterfaceNormalizer._parse_cisco_to_config(raw)
        elif vendor_lower == "huawei" or vendor == "HUAWEI_VRP":
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
        Parse Cisco IOS-XE Native response to InterfaceConfig
        
        Native structure:
        - Cisco-IOS-XE-native:{Type}: [{ name, ip.address.primary, shutdown, ... }]
        """
        # Find the interface entry from native response
        iface = {}
        iface_type = ""
        for key, value in raw.items():
            if key.startswith("Cisco-IOS-XE-native:"):
                iface_type = key.replace("Cisco-IOS-XE-native:", "")
                if isinstance(value, list) and value:
                    iface = value[0]
                elif isinstance(value, dict):
                    iface = value
                break
        
        if not iface:
            iface = raw
        
        # Build full name
        iface_num = str(iface.get("name", ""))
        name = f"{iface_type}{iface_num}" if iface_type else iface_num
        
        # Admin status: shutdown leaf present = disabled
        enabled = "shutdown" not in iface
        description = iface.get("description")
        mtu = iface.get("mtu")
        
        # Extract IP from ip.address.primary (native structure)
        ip = None
        mask = None
        ip_block = iface.get("ip", {})
        address_block = ip_block.get("address", {})
        primary = address_block.get("primary", {})
        if primary:
            ip = primary.get("address")
            mask = primary.get("mask")
        
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

