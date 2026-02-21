"""
System Normalizer
แปลง vendor-specific system response เป็น Unified format
"""
from typing import Any, Dict, List
from app.schemas.unified import (
    UnifiedSystemInfo,
    UnifiedRunningConfig,
    RunningConfigInterface,
    RunningConfigRoute,
    RunningConfigOspf,
    RunningConfigSystem,
)


class SystemNormalizer:
    """
    Normalize system responses from different vendors to unified format
    """
    
    def normalize_show_version(self, driver_used: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize show version response"""
        
        if driver_used == "CISCO_IOS_XE":
            return self._normalize_cisco_version(raw)
        
        if driver_used == "HUAWEI_VRP":
            return self._normalize_huawei_version(raw)

        return {"vendor": driver_used, "raw": raw}
    
    def normalize_show_running_config(self, driver_used: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize running config response → structured JSON for frontend"""
        
        if driver_used == "CISCO_IOS_XE":
            return self._normalize_cisco_running_config(raw)
        
        if driver_used == "HUAWEI_VRP":
            return self._normalize_huawei_running_config(raw)
        
        
        # Fallback: return raw with vendor info
        return UnifiedRunningConfig(
            vendor=driver_used,
            raw_config=raw,
        ).model_dump()
    
    
    # =========================================================
    # Cisco Normalizers
    # =========================================================
    
    def _normalize_cisco_version(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Cisco version info"""
        native = raw.get("Cisco-IOS-XE-native:native") or raw
        version = native.get("version") or raw.get("Cisco-IOS-XE-native:version")
        
        out = UnifiedSystemInfo(
            hostname=native.get("hostname", "unknown"),
            vendor="cisco",
            model=native.get("license", {}).get("udi", {}).get("pid"),
            serial_number=native.get("license", {}).get("udi", {}).get("sn"),
            software_version=str(version) if version else None,
        )
        return out.model_dump()
    
    def _normalize_cisco_running_config(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Cisco IOS-XE native running config
        Parse Cisco-IOS-XE-native:native → structured JSON
        """
        native = raw.get("Cisco-IOS-XE-native:native") or raw
        
        hostname = native.get("hostname")
        version = native.get("version")
        
        # --- Parse Interfaces ---
        interfaces = self._parse_cisco_interfaces(native)
        
        # --- Parse Static Routes ---
        routes = self._parse_cisco_static_routes(native)
        
        # --- Parse OSPF ---
        ospf = self._parse_cisco_ospf(native)
        
        # --- Parse System Services ---
        system = self._parse_cisco_system(native, hostname)
        
        out = UnifiedRunningConfig(
            hostname=hostname,
            version=str(version) if version else None,
            vendor="cisco",
            interfaces=interfaces,
            static_routes=routes,
            ospf=ospf,
            system=system,
            raw_config=raw,
        )
        return out.model_dump()
    
    def _parse_cisco_interfaces(self, native: Dict[str, Any]) -> List[RunningConfigInterface]:
        """Parse Cisco interfaces from native config"""
        interfaces: List[RunningConfigInterface] = []
        iface_section = native.get("interface", {})
        
        # Cisco groups interfaces by type: GigabitEthernet, Loopback, etc.
        for iface_type, iface_list in iface_section.items():
            if not isinstance(iface_list, list):
                iface_list = [iface_list]
            
            for iface in iface_list:
                if not isinstance(iface, dict):
                    continue
                
                name_part = iface.get("name", "")
                full_name = f"{iface_type}{name_part}"
                
                # Parse IP address
                ip_addr = None
                ip_config = iface.get("ip", {}).get("address", {}).get("primary", {})
                if ip_config:
                    ip = ip_config.get("address")
                    mask = ip_config.get("mask")
                    if ip and mask:
                        prefix_len = self._mask_to_prefix(mask)
                        ip_addr = f"{ip}/{prefix_len}"
                
                # Parse shutdown state
                enabled = "shutdown" not in iface
                
                interfaces.append(RunningConfigInterface(
                    name=full_name,
                    type=iface_type,
                    ip_address=ip_addr,
                    enabled=enabled,
                    description=iface.get("description"),
                    mtu=iface.get("mtu"),
                ))
        
        return interfaces
    
    def _parse_cisco_static_routes(self, native: Dict[str, Any]) -> List[RunningConfigRoute]:
        """Parse Cisco static routes from native config"""
        routes: List[RunningConfigRoute] = []
        
        ip_route = native.get("ip", {}).get("route", {})
        
        # ip route static routes
        statics = ip_route.get("ip-route-interface-forwarding-list", [])
        if not isinstance(statics, list):
            statics = [statics]
        
        for r in statics:
            if not isinstance(r, dict):
                continue
            prefix = r.get("prefix", "")
            mask = r.get("mask", "")
            fwd_list = r.get("fwd-list", [])
            if not isinstance(fwd_list, list):
                fwd_list = [fwd_list]
            
            for fwd in fwd_list:
                if not isinstance(fwd, dict):
                    continue
                nh = fwd.get("fwd")
                prefix_len = self._mask_to_prefix(mask) if mask else ""
                routes.append(RunningConfigRoute(
                    prefix=f"{prefix}/{prefix_len}" if prefix_len else prefix,
                    next_hop=nh,
                ))
        
        # Also try vrf routes
        vrf_routes = ip_route.get("vrf", [])
        if isinstance(vrf_routes, list):
            for vrf in vrf_routes:
                vrf_statics = vrf.get("ip-route-interface-forwarding-list", [])
                if not isinstance(vrf_statics, list):
                    vrf_statics = [vrf_statics]
                for r in vrf_statics:
                    if not isinstance(r, dict):
                        continue
                    prefix = r.get("prefix", "")
                    mask = r.get("mask", "")
                    fwd_list = r.get("fwd-list", [])
                    if not isinstance(fwd_list, list):
                        fwd_list = [fwd_list]
                    for fwd in fwd_list:
                        if not isinstance(fwd, dict):
                            continue
                        nh = fwd.get("fwd")
                        prefix_len = self._mask_to_prefix(mask) if mask else ""
                        routes.append(RunningConfigRoute(
                            prefix=f"{prefix}/{prefix_len}" if prefix_len else prefix,
                            next_hop=nh,
                        ))
        
        return routes
    
    def _parse_cisco_ospf(self, native: Dict[str, Any]) -> RunningConfigOspf | None:
        """Parse Cisco OSPF config from native config"""
        router = native.get("router", {})
        ospf_config = router.get("Cisco-IOS-XE-ospf:router-ospf", {})
        ospf_list = ospf_config.get("ospf", {}).get("process-id", [])
        
        if not ospf_list:
            return None
        
        if not isinstance(ospf_list, list):
            ospf_list = [ospf_list]
        
        # Take first OSPF process
        ospf = ospf_list[0]
        process_id = ospf.get("id")
        router_id = ospf.get("router-id")
        
        # Parse networks
        networks = []
        net_list = ospf.get("network", [])
        if not isinstance(net_list, list):
            net_list = [net_list]
        for n in net_list:
            if isinstance(n, dict):
                networks.append({
                    "ip": n.get("ip"),
                    "wildcard": n.get("wildcard"),
                    "area": n.get("area"),
                })
        
        # Parse passive interfaces
        passive = []
        passive_iface = ospf.get("passive-interface", {})
        if isinstance(passive_iface, dict):
            iface_list = passive_iface.get("interface", [])
            if isinstance(iface_list, list):
                passive = iface_list
            elif isinstance(iface_list, str):
                passive = [iface_list]
        
        return RunningConfigOspf(
            process_id=int(process_id) if process_id else None,
            router_id=router_id,
            networks=networks,
            passive_interfaces=passive,
        )
    
    def _parse_cisco_system(self, native: Dict[str, Any], hostname: str = None) -> RunningConfigSystem:
        """Parse Cisco system services"""
        # Domain name
        domain_name = native.get("ip", {}).get("domain", {}).get("name")
        
        # NTP servers
        ntp_servers = []
        ntp = native.get("ntp", {})
        ntp_server_list = ntp.get("Cisco-IOS-XE-ntp:server", {}).get("server-list", [])
        if not isinstance(ntp_server_list, list):
            ntp_server_list = [ntp_server_list]
        for s in ntp_server_list:
            if isinstance(s, dict):
                addr = s.get("ip-address")
                if addr:
                    ntp_servers.append(addr)
        
        # DNS servers
        dns_servers = []
        name_server = native.get("ip", {}).get("name-server", {})
        ns_list = name_server.get("no-vrf", []) if isinstance(name_server, dict) else []
        if isinstance(ns_list, list):
            dns_servers = [str(ns) for ns in ns_list if ns]
        elif isinstance(ns_list, str):
            dns_servers = [ns_list]
        
        # Banner
        banner = None
        banner_config = native.get("banner", {})
        if isinstance(banner_config, dict):
            motd = banner_config.get("motd", {})
            if isinstance(motd, dict):
                banner = motd.get("banner", "")
        
        return RunningConfigSystem(
            hostname=hostname,
            domain_name=domain_name,
            ntp_servers=ntp_servers,
            dns_servers=dns_servers,
            banner=banner,
        )
    
    # =========================================================
    # Huawei Normalizers
    # =========================================================
    
    def _normalize_huawei_version(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Huawei version info"""
        system = raw.get("huawei-system:system") or raw
        
        out = UnifiedSystemInfo(
            hostname=system.get("hostName", "unknown"),
            vendor="huawei",
            model=system.get("productName"),
            serial_number=system.get("esn"),
            software_version=system.get("vrpVersion"),
            uptime=system.get("upTime"),
        )
        return out.model_dump()
    
    def _normalize_huawei_running_config(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Huawei running config
        Parse huawei YANG modules → structured JSON
        """
        interfaces: List[RunningConfigInterface] = []
        routes: List[RunningConfigRoute] = []
        hostname = None
        
        # Parse system
        system_raw = raw.get("huawei-system:system") or raw.get("system") or {}
        hostname = system_raw.get("hostName")
        
        # Parse interfaces
        iface_section = (
            raw.get("huawei-ifm:ifm", {}).get("interfaces", {}).get("interface", [])
            or raw.get("ifm", {}).get("interfaces", {}).get("interface", [])
        )
        for iface in iface_section:
            if not isinstance(iface, dict):
                continue
            name = iface.get("ifName", "")
            ip_addr = None
            
            # Parse IPv4
            ipv4 = iface.get("ifmAm4", {})
            addrs = ipv4.get("am4CfgAddrs", {}).get("am4CfgAddr", [])
            if not isinstance(addrs, list):
                addrs = [addrs]
            if addrs and isinstance(addrs[0], dict):
                ip = addrs[0].get("ifIpAddr")
                mask = addrs[0].get("subnetMask")
                if ip and mask:
                    prefix_len = self._mask_to_prefix(mask)
                    ip_addr = f"{ip}/{prefix_len}"
            
            enabled = iface.get("ifAdminStatus", "").lower() != "down"
            
            interfaces.append(RunningConfigInterface(
                name=name,
                type=iface.get("ifType"),
                ip_address=ip_addr,
                enabled=enabled,
                description=iface.get("ifDescr"),
                mtu=iface.get("ifMtu"),
            ))
        
        # Parse static routes
        static_section = (
            raw.get("huawei-staticrt:staticrt", {}).get("staticrtbase", {}).get("srRoutes", {}).get("srRoute", [])
        )
        if not isinstance(static_section, list):
            static_section = [static_section] if static_section else []
        for r in static_section:
            if not isinstance(r, dict):
                continue
            prefix = r.get("prefix", "")
            mask_len = r.get("maskLength", "")
            nh = r.get("nexthop") or r.get("ifName")
            routes.append(RunningConfigRoute(
                prefix=f"{prefix}/{mask_len}" if mask_len else prefix,
                next_hop=str(nh) if nh else None,
            ))
        
        # Parse OSPF
        ospf = self._parse_huawei_ospf(raw)
        
        out = UnifiedRunningConfig(
            hostname=hostname,
            vendor="huawei",
            interfaces=interfaces,
            static_routes=routes,
            ospf=ospf,
            system=RunningConfigSystem(hostname=hostname) if hostname else None,
            raw_config=raw,
        )
        return out.model_dump()
    
    def _parse_huawei_ospf(self, raw: Dict[str, Any]) -> RunningConfigOspf | None:
        """Parse Huawei OSPF config"""
        ospf_raw = (
            raw.get("huawei-ospfv2:ospfv2", {}).get("ospfSites", {}).get("ospfSite", [])
        )
        if not ospf_raw:
            return None
        
        if not isinstance(ospf_raw, list):
            ospf_raw = [ospf_raw]
        
        ospf = ospf_raw[0]
        process_id = ospf.get("processId")
        router_id = ospf.get("routerId")
        
        networks = []
        areas = ospf.get("ospfAreas", {}).get("ospfArea", [])
        if not isinstance(areas, list):
            areas = [areas]
        for area in areas:
            if not isinstance(area, dict):
                continue
            area_id = area.get("areaId")
            nets = area.get("networks", {}).get("network", [])
            if not isinstance(nets, list):
                nets = [nets]
            for n in nets:
                if isinstance(n, dict):
                    networks.append({
                        "ip": n.get("address"),
                        "wildcard": n.get("wildcardMask"),
                        "area": area_id,
                    })
        
        return RunningConfigOspf(
            process_id=int(process_id) if process_id else None,
            router_id=router_id,
            networks=networks,
        )
    
    # =========================================================
    # Utility Helpers
    # =========================================================
    
    @staticmethod
    def _mask_to_prefix(mask: str) -> int:
        """Convert subnet mask (255.255.255.0) to prefix length (24)"""
        try:
            parts = mask.split(".")
            if len(parts) != 4:
                return 0
            binary = "".join(f"{int(p):08b}" for p in parts)
            return binary.count("1")
        except (ValueError, AttributeError):
            return 0
