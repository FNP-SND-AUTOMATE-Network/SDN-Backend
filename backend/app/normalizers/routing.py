"""
Routing Normalizer
แปลง routing responses จากหลาย vendors ให้เป็น Unified format
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel


class RouteEntry(BaseModel):
    """Single route entry"""
    prefix: str                    # e.g., "10.0.0.0/24"
    next_hop: Optional[str]        # e.g., "192.168.1.1"
    interface: Optional[str]       # e.g., "GigabitEthernet1"
    protocol: str                  # "static", "connected", "ospf", "bgp"
    metric: Optional[int]          # Route metric
    preference: Optional[int]      # Administrative distance
    active: bool                   # Is route active/installed


class UnifiedRoutingTable(BaseModel):
    """Unified routing table response"""
    device_id: str
    vendor: str
    timestamp: str
    route_count: int
    routes: List[RouteEntry]
    raw: Dict[str, Any]            # Original vendor response


class RoutingNormalizer:
    """Normalize routing data from different vendors"""
    
    @staticmethod
    def normalize(
        raw: Dict[str, Any],
        device_id: str,
        vendor: str
    ) -> UnifiedRoutingTable:
        """
        Main normalize entry point
        Dispatch based on vendor/model type
        """
        routes = []
        
        # Detect format and normalize
        if "openconfig-network-instance:static-routes" in str(raw):
            routes = RoutingNormalizer._parse_openconfig(raw)
        elif "Cisco-IOS-XE-native:route" in str(raw) or "ip-route-interface-forwarding-list" in str(raw):
            routes = RoutingNormalizer._parse_cisco(raw)
        elif "huawei-routing:routing" in str(raw):
            routes = RoutingNormalizer._parse_huawei(raw)
        else:
            # Try generic parse
            routes = RoutingNormalizer._parse_generic(raw)
        
        return UnifiedRoutingTable(
            device_id=device_id,
            vendor=vendor,
            timestamp=datetime.utcnow().isoformat() + "Z",
            route_count=len(routes),
            routes=routes,
            raw=raw
        )

    @staticmethod
    def _parse_openconfig(raw: Dict[str, Any]) -> List[RouteEntry]:
        """Parse OpenConfig network-instance static routes"""
        routes = []
        
        try:
            # Navigate OpenConfig structure
            # openconfig-network-instance:network-instances
            network_instances = raw.get("openconfig-network-instance:network-instances", {})
            instances = network_instances.get("network-instance", [])
            
            for instance in instances:
                protocols = instance.get("protocols", {}).get("protocol", [])
                
                for protocol in protocols:
                    proto_name = protocol.get("name", "unknown")
                    proto_id = protocol.get("identifier", "")
                    
                    if "STATIC" in str(proto_id):
                        static_routes = protocol.get("static-routes", {}).get("static", [])
                        
                        for static in static_routes:
                            prefix = static.get("prefix", "")
                            next_hops = static.get("next-hops", {}).get("next-hop", [])
                            
                            for nh in next_hops:
                                nh_config = nh.get("config", {})
                                routes.append(RouteEntry(
                                    prefix=prefix,
                                    next_hop=nh_config.get("next-hop"),
                                    interface=nh.get("interface-ref", {}).get("config", {}).get("interface"),
                                    protocol="static",
                                    metric=nh_config.get("metric"),
                                    preference=None,
                                    active=True
                                ))
        except Exception:
            pass
        
        return routes

    @staticmethod
    def _parse_cisco(raw: Dict[str, Any]) -> List[RouteEntry]:
        """Parse Cisco IOS-XE native routing"""
        routes = []
        
        try:
            # Cisco native format
            ip_route = raw.get("Cisco-IOS-XE-native:route", {})
            static_routes = ip_route.get("ip-route-interface-forwarding-list", [])
            
            if isinstance(static_routes, dict):
                static_routes = [static_routes]
            
            for route in static_routes:
                prefix = route.get("prefix", "0.0.0.0")
                mask = route.get("mask", "0.0.0.0")
                prefix_str = f"{prefix}/{_mask_to_prefix(mask)}"
                
                fwd_list = route.get("fwd-list", [])
                if isinstance(fwd_list, dict):
                    fwd_list = [fwd_list]
                
                for fwd in fwd_list:
                    routes.append(RouteEntry(
                        prefix=prefix_str,
                        next_hop=fwd.get("fwd"),
                        interface=fwd.get("interface"),
                        protocol="static",
                        metric=fwd.get("metric"),
                        preference=fwd.get("global", {}).get("distance"),
                        active=True
                    ))
        except Exception:
            pass
        
        return routes

    @staticmethod
    def _parse_huawei(raw: Dict[str, Any]) -> List[RouteEntry]:
        """Parse Huawei routing table"""
        routes = []
        
        try:
            routing = raw.get("huawei-routing:routing", {})
            static_routing = routing.get("static-routing", {})
            static_routes = static_routing.get("route-entries", {}).get("route-entry", [])
            
            if isinstance(static_routes, dict):
                static_routes = [static_routes]
            
            for route in static_routes:
                prefix = route.get("dest-address", "0.0.0.0")
                mask = route.get("mask-length", 24)
                
                routes.append(RouteEntry(
                    prefix=f"{prefix}/{mask}",
                    next_hop=route.get("nexthop", {}).get("nexthop-address"),
                    interface=route.get("interface-name"),
                    protocol="static",
                    metric=route.get("metric"),
                    preference=route.get("preference"),
                    active=route.get("state") == "active"
                ))
        except Exception:
            pass
        
        return routes

    @staticmethod
    def _parse_generic(raw: Dict[str, Any]) -> List[RouteEntry]:
        """Generic fallback parser"""
        routes = []
        
        # Try to find route-like data
        def find_routes(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    key_lower = k.lower()
                    if "route" in key_lower and isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict):
                                entry = RouteEntry(
                                    prefix=item.get("prefix", item.get("dest", "unknown")),
                                    next_hop=item.get("next-hop", item.get("nexthop")),
                                    interface=item.get("interface"),
                                    protocol=item.get("protocol", "unknown"),
                                    metric=item.get("metric"),
                                    preference=item.get("preference"),
                                    active=True
                                )
                                routes.append(entry)
                    else:
                        find_routes(v, f"{path}/{k}")
            elif isinstance(obj, list):
                for item in obj:
                    find_routes(item, path)
        
        find_routes(raw)
        return routes


class InterfaceBriefEntry(BaseModel):
    """Single interface brief entry"""
    interface: str
    ip_address: Optional[str]
    status: str                    # "up", "down", "admin-down"
    protocol: str                  # "up", "down"
    method: Optional[str]          # "manual", "dhcp"


class UnifiedInterfaceBrief(BaseModel):
    """Unified show ip interface brief response"""
    device_id: str
    vendor: str
    timestamp: str
    interface_count: int
    interfaces: List[InterfaceBriefEntry]
    raw: Dict[str, Any]


class InterfaceBriefNormalizer:
    """Normalize IP interface brief data"""
    
    @staticmethod
    def normalize(
        raw: Dict[str, Any],
        device_id: str,
        vendor: str
    ) -> UnifiedInterfaceBrief:
        """Normalize interface brief response"""
        interfaces = []
        
        # Detect and parse
        if "ietf-interfaces:interfaces" in str(raw) or "interfaces-state" in str(raw):
            interfaces = InterfaceBriefNormalizer._parse_ietf(raw)
        elif "openconfig-interfaces:interfaces" in str(raw):
            interfaces = InterfaceBriefNormalizer._parse_openconfig(raw)
        elif "huawei-ifm:interfaces" in str(raw):
            interfaces = InterfaceBriefNormalizer._parse_huawei(raw)
        else:
            interfaces = InterfaceBriefNormalizer._parse_generic(raw)
        
        return UnifiedInterfaceBrief(
            device_id=device_id,
            vendor=vendor,
            timestamp=datetime.utcnow().isoformat() + "Z",
            interface_count=len(interfaces),
            interfaces=interfaces,
            raw=raw
        )

    @staticmethod
    def _parse_ietf(raw: Dict[str, Any]) -> List[InterfaceBriefEntry]:
        """Parse IETF interfaces (used by Cisco via NETCONF)"""
        interfaces = []
        
        try:
            # Check for interfaces-state (operational)
            if "ietf-interfaces:interfaces-state" in raw:
                ifaces = raw["ietf-interfaces:interfaces-state"].get("interface", [])
            elif "interfaces-state" in raw:
                ifaces = raw["interfaces-state"].get("interface", [])
            else:
                ifaces = raw.get("ietf-interfaces:interfaces", {}).get("interface", [])
            
            if isinstance(ifaces, dict):
                ifaces = [ifaces]
            
            for iface in ifaces:
                name = iface.get("name", "unknown")
                oper_status = iface.get("oper-status", "down")
                admin_status = iface.get("admin-status", "down")
                
                # Get IP from ipv4
                ip_addr = None
                ipv4 = iface.get("ietf-ip:ipv4", {})
                addresses = ipv4.get("address", [])
                if addresses:
                    if isinstance(addresses, dict):
                        addresses = [addresses]
                    ip_addr = addresses[0].get("ip")
                
                # Determine status
                if admin_status == "down":
                    status = "admin-down"
                else:
                    status = "up" if oper_status == "up" else "down"
                
                interfaces.append(InterfaceBriefEntry(
                    interface=name,
                    ip_address=ip_addr,
                    status=status,
                    protocol="up" if oper_status == "up" else "down",
                    method="manual"
                ))
        except Exception:
            pass
        
        return interfaces

    @staticmethod
    def _parse_openconfig(raw: Dict[str, Any]) -> List[InterfaceBriefEntry]:
        """Parse OpenConfig interfaces"""
        interfaces = []
        
        try:
            oc_ifaces = raw.get("openconfig-interfaces:interfaces", {}).get("interface", [])
            
            if isinstance(oc_ifaces, dict):
                oc_ifaces = [oc_ifaces]
            
            for iface in oc_ifaces:
                name = iface.get("name", "unknown")
                state = iface.get("state", {})
                
                # Get IP
                ip_addr = None
                subifs = iface.get("subinterfaces", {}).get("subinterface", [])
                if subifs:
                    if isinstance(subifs, dict):
                        subifs = [subifs]
                    ipv4 = subifs[0].get("openconfig-if-ip:ipv4", {})
                    addrs = ipv4.get("addresses", {}).get("address", [])
                    if addrs:
                        if isinstance(addrs, dict):
                            addrs = [addrs]
                        ip_addr = addrs[0].get("state", {}).get("ip")
                
                oper_status = state.get("oper-status", "DOWN")
                admin_status = state.get("admin-status", "DOWN")
                
                if admin_status == "DOWN":
                    status = "admin-down"
                else:
                    status = "up" if oper_status == "UP" else "down"
                
                interfaces.append(InterfaceBriefEntry(
                    interface=name,
                    ip_address=ip_addr,
                    status=status,
                    protocol="up" if oper_status == "UP" else "down",
                    method="manual"
                ))
        except Exception:
            pass
        
        return interfaces

    @staticmethod
    def _parse_huawei(raw: Dict[str, Any]) -> List[InterfaceBriefEntry]:
        """Parse Huawei interfaces"""
        interfaces = []
        
        try:
            hw_ifaces = raw.get("huawei-ifm:interfaces", {}).get("interface", [])
            
            if isinstance(hw_ifaces, dict):
                hw_ifaces = [hw_ifaces]
            
            for iface in hw_ifaces:
                name = iface.get("name", "unknown")
                
                # Get IP from ipv4
                ip_addr = None
                ipv4 = iface.get("ipv4", {})
                addresses = ipv4.get("addresses", {}).get("address", [])
                if addresses:
                    if isinstance(addresses, dict):
                        addresses = [addresses]
                    ip_addr = addresses[0].get("ip")
                
                oper_status = iface.get("dynamic", {}).get("operational-status", "down")
                admin_status = iface.get("admin-status", "down")
                
                if admin_status == "down":
                    status = "admin-down"
                else:
                    status = "up" if oper_status == "up" else "down"
                
                interfaces.append(InterfaceBriefEntry(
                    interface=name,
                    ip_address=ip_addr,
                    status=status,
                    protocol="up" if oper_status == "up" else "down",
                    method="manual"
                ))
        except Exception:
            pass
        
        return interfaces

    @staticmethod
    def _parse_generic(raw: Dict[str, Any]) -> List[InterfaceBriefEntry]:
        """Generic fallback"""
        interfaces = []
        
        def find_interfaces(obj):
            if isinstance(obj, dict):
                if "name" in obj and ("status" in obj or "oper-status" in obj):
                    interfaces.append(InterfaceBriefEntry(
                        interface=obj.get("name", "unknown"),
                        ip_address=obj.get("ip-address"),
                        status=obj.get("status", obj.get("oper-status", "unknown")),
                        protocol=obj.get("protocol-status", "unknown"),
                        method=None
                    ))
                for v in obj.values():
                    find_interfaces(v)
            elif isinstance(obj, list):
                for item in obj:
                    find_interfaces(item)
        
        find_interfaces(raw)
        return interfaces


# ===== Utility Functions =====
def _mask_to_prefix(mask: str) -> int:
    """Convert dotted decimal netmask to CIDR prefix length"""
    try:
        parts = mask.split(".")
        binary = "".join(format(int(p), "08b") for p in parts)
        return binary.count("1")
    except:
        return 24


# ===== OSPF Models =====
class OspfNeighborEntry(BaseModel):
    """Single OSPF neighbor entry"""
    neighbor_id: str               # Router ID of neighbor
    neighbor_address: str          # IP address of neighbor
    state: str                     # "FULL", "2WAY", "INIT", etc.
    interface: Optional[str]       # Interface name
    area: Optional[str]            # OSPF area
    priority: Optional[int]        # Neighbor priority
    dr: Optional[str]              # Designated Router
    bdr: Optional[str]             # Backup Designated Router


class UnifiedOspfNeighbors(BaseModel):
    """Unified OSPF neighbors response"""
    device_id: str
    vendor: str
    timestamp: str
    neighbor_count: int
    neighbors: List[OspfNeighborEntry]
    raw: Dict[str, Any]


class OspfLsaEntry(BaseModel):
    """Single OSPF LSA entry"""
    lsa_type: str                  # "Router", "Network", "Summary", etc.
    link_state_id: str
    advertising_router: str
    sequence_number: Optional[str]
    age: Optional[int]
    area: Optional[str]


class UnifiedOspfDatabase(BaseModel):
    """Unified OSPF LSDB response"""
    device_id: str
    vendor: str
    timestamp: str
    lsa_count: int
    lsas: List[OspfLsaEntry]
    raw: Dict[str, Any]


class OspfNormalizer:
    """Normalize OSPF data from different vendors"""
    
    @staticmethod
    def normalize_neighbors(
        raw: Dict[str, Any],
        device_id: str,
        vendor: str
    ) -> UnifiedOspfNeighbors:
        """Normalize OSPF neighbors response"""
        neighbors = []
        
        if "openconfig-ospfv2" in str(raw) or "ospfv2" in str(raw):
            neighbors = OspfNormalizer._parse_openconfig_neighbors(raw)
        elif "Cisco-IOS-XE-ospf-oper" in str(raw) or "ospf-oper-data" in str(raw):
            neighbors = OspfNormalizer._parse_cisco_neighbors(raw)
        else:
            neighbors = OspfNormalizer._parse_generic_neighbors(raw)
        
        return UnifiedOspfNeighbors(
            device_id=device_id,
            vendor=vendor,
            timestamp=datetime.utcnow().isoformat() + "Z",
            neighbor_count=len(neighbors),
            neighbors=neighbors,
            raw=raw
        )

    @staticmethod
    def normalize_database(
        raw: Dict[str, Any],
        device_id: str,
        vendor: str
    ) -> UnifiedOspfDatabase:
        """Normalize OSPF LSDB response"""
        lsas = []
        
        if "openconfig-ospfv2" in str(raw):
            lsas = OspfNormalizer._parse_openconfig_lsdb(raw)
        elif "Cisco-IOS-XE-ospf-oper" in str(raw):
            lsas = OspfNormalizer._parse_cisco_lsdb(raw)
        else:
            lsas = OspfNormalizer._parse_generic_lsdb(raw)
        
        return UnifiedOspfDatabase(
            device_id=device_id,
            vendor=vendor,
            timestamp=datetime.utcnow().isoformat() + "Z",
            lsa_count=len(lsas),
            lsas=lsas,
            raw=raw
        )

    @staticmethod
    def _parse_openconfig_neighbors(raw: Dict[str, Any]) -> List[OspfNeighborEntry]:
        """Parse OpenConfig OSPF neighbors"""
        neighbors = []
        
        try:
            # Navigate OpenConfig structure
            areas = raw.get("openconfig-ospfv2:areas", {}).get("area", [])
            if isinstance(areas, dict):
                areas = [areas]
            
            for area in areas:
                area_id = area.get("identifier", "0")
                interfaces = area.get("interfaces", {}).get("interface", [])
                
                if isinstance(interfaces, dict):
                    interfaces = [interfaces]
                
                for iface in interfaces:
                    iface_name = iface.get("id", "")
                    nbrs = iface.get("neighbors", {}).get("neighbor", [])
                    
                    if isinstance(nbrs, dict):
                        nbrs = [nbrs]
                    
                    for nbr in nbrs:
                        state = nbr.get("state", {})
                        neighbors.append(OspfNeighborEntry(
                            neighbor_id=nbr.get("router-id", state.get("router-id", "")),
                            neighbor_address=state.get("address", ""),
                            state=state.get("adjacency-state", "UNKNOWN"),
                            interface=iface_name,
                            area=str(area_id),
                            priority=state.get("priority"),
                            dr=state.get("designated-router"),
                            bdr=state.get("backup-designated-router")
                        ))
        except Exception:
            pass
        
        return neighbors

    @staticmethod
    def _parse_cisco_neighbors(raw: Dict[str, Any]) -> List[OspfNeighborEntry]:
        """Parse Cisco IOS-XE OSPF neighbors"""
        neighbors = []
        
        try:
            # Cisco OSPF operational data
            ospf_areas = raw.get("Cisco-IOS-XE-ospf-oper:ospf-area", [])
            if isinstance(ospf_areas, dict):
                ospf_areas = [ospf_areas]
            
            for area in ospf_areas:
                area_id = area.get("area-id", "0")
                interfaces = area.get("ospf-interface", [])
                
                if isinstance(interfaces, dict):
                    interfaces = [interfaces]
                
                for iface in interfaces:
                    iface_name = iface.get("name", "")
                    nbrs = iface.get("ospf-neighbor", [])
                    
                    if isinstance(nbrs, dict):
                        nbrs = [nbrs]
                    
                    for nbr in nbrs:
                        neighbors.append(OspfNeighborEntry(
                            neighbor_id=nbr.get("neighbor-id", ""),
                            neighbor_address=nbr.get("address", ""),
                            state=nbr.get("state", "UNKNOWN"),
                            interface=iface_name,
                            area=str(area_id),
                            priority=nbr.get("priority"),
                            dr=nbr.get("dr"),
                            bdr=nbr.get("bdr")
                        ))
        except Exception:
            pass
        
        return neighbors

    @staticmethod
    def _parse_generic_neighbors(raw: Dict[str, Any]) -> List[OspfNeighborEntry]:
        """Generic fallback for OSPF neighbors"""
        neighbors = []
        
        def find_neighbors(obj):
            if isinstance(obj, dict):
                if "neighbor-id" in obj or "router-id" in obj:
                    neighbors.append(OspfNeighborEntry(
                        neighbor_id=obj.get("neighbor-id", obj.get("router-id", "unknown")),
                        neighbor_address=obj.get("address", obj.get("neighbor-address", "")),
                        state=obj.get("state", obj.get("adjacency-state", "UNKNOWN")),
                        interface=obj.get("interface"),
                        area=obj.get("area"),
                        priority=obj.get("priority"),
                        dr=obj.get("dr"),
                        bdr=obj.get("bdr")
                    ))
                for v in obj.values():
                    find_neighbors(v)
            elif isinstance(obj, list):
                for item in obj:
                    find_neighbors(item)
        
        find_neighbors(raw)
        return neighbors

    @staticmethod
    def _parse_openconfig_lsdb(raw: Dict[str, Any]) -> List[OspfLsaEntry]:
        """Parse OpenConfig OSPF LSDB"""
        lsas = []
        
        try:
            areas = raw.get("openconfig-ospfv2:areas", {}).get("area", [])
            if isinstance(areas, dict):
                areas = [areas]
            
            for area in areas:
                area_id = area.get("identifier", "0")
                lsdb = area.get("lsdb", {})
                lsa_types = lsdb.get("lsa-types", {}).get("lsa-type", [])
                
                if isinstance(lsa_types, dict):
                    lsa_types = [lsa_types]
                
                for lsa_type in lsa_types:
                    type_name = lsa_type.get("type", "")
                    lsa_list = lsa_type.get("lsas", {}).get("lsa", [])
                    
                    if isinstance(lsa_list, dict):
                        lsa_list = [lsa_list]
                    
                    for lsa in lsa_list:
                        state = lsa.get("state", {})
                        lsas.append(OspfLsaEntry(
                            lsa_type=type_name,
                            link_state_id=lsa.get("link-state-id", ""),
                            advertising_router=lsa.get("advertising-router", ""),
                            sequence_number=state.get("sequence-number"),
                            age=state.get("age"),
                            area=str(area_id)
                        ))
        except Exception:
            pass
        
        return lsas

    @staticmethod
    def _parse_cisco_lsdb(raw: Dict[str, Any]) -> List[OspfLsaEntry]:
        """Parse Cisco IOS-XE OSPF LSDB"""
        lsas = []
        
        try:
            lsa_scopes = raw.get("Cisco-IOS-XE-ospf-oper:link-scope-lsas", {})
            lsa_scope = lsa_scopes.get("link-scope-lsa", [])
            
            if isinstance(lsa_scope, dict):
                lsa_scope = [lsa_scope]
            
            for scope in lsa_scope:
                lsa_type = scope.get("lsa-type", "")
                lsa_list = scope.get("link-scope-lsa-id", [])
                
                if isinstance(lsa_list, dict):
                    lsa_list = [lsa_list]
                
                for lsa in lsa_list:
                    lsas.append(OspfLsaEntry(
                        lsa_type=str(lsa_type),
                        link_state_id=lsa.get("link-state-id", ""),
                        advertising_router=lsa.get("adv-router", ""),
                        sequence_number=lsa.get("seq-num"),
                        age=lsa.get("age"),
                        area=lsa.get("area-id")
                    ))
        except Exception:
            pass
        
        return lsas

    @staticmethod
    def _parse_generic_lsdb(raw: Dict[str, Any]) -> List[OspfLsaEntry]:
        """Generic fallback for OSPF LSDB"""
        lsas = []
        
        def find_lsas(obj):
            if isinstance(obj, dict):
                if "link-state-id" in obj or "lsa-id" in obj:
                    lsas.append(OspfLsaEntry(
                        lsa_type=obj.get("lsa-type", obj.get("type", "unknown")),
                        link_state_id=obj.get("link-state-id", obj.get("lsa-id", "")),
                        advertising_router=obj.get("advertising-router", obj.get("adv-router", "")),
                        sequence_number=obj.get("sequence-number", obj.get("seq-num")),
                        age=obj.get("age"),
                        area=obj.get("area-id", obj.get("area"))
                    ))
                for v in obj.values():
                    find_lsas(v)
            elif isinstance(obj, list):
                for item in obj:
                    find_lsas(item)
        
        find_lsas(raw)
        return lsas