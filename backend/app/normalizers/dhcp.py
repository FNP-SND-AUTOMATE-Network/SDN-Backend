"""
DHCP Normalizer
แปลง vendor-specific DHCP response เป็น Unified format
"""
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from typing import Optional


# ===== DHCP Unified Schemas =====
class UnifiedDhcpPool(BaseModel):
    """Single DHCP pool entry"""
    pool_name: str
    gateway: Optional[str] = None
    subnet_mask: Optional[str] = None
    start_ip: Optional[str] = None
    end_ip: Optional[str] = None
    dns_servers: List[str] = []
    lease_days: Optional[int] = None
    status: str = "active"


class UnifiedDhcpPoolList(BaseModel):
    """DHCP pool list"""
    pools: List[UnifiedDhcpPool] = []
    total_count: int = 0


class DhcpNormalizer:
    """Normalize DHCP responses from different vendors to unified format"""
    
    def normalize_show_dhcp_pools(self, driver_used: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize show dhcp pools response → unified DHCP pool list"""
        
        if driver_used == "huawei" or driver_used == "HUAWEI_VRP":
            return self._normalize_huawei_dhcp(raw)
        
        if driver_used == "cisco" or driver_used == "IOS_XE":
            return self._normalize_cisco_dhcp(raw)
        
        # Fallback
        return UnifiedDhcpPoolList(pools=[], total_count=0).model_dump()
    
    # =========================================================
    # Huawei
    # =========================================================
    
    def _normalize_huawei_dhcp(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse Huawei ip-pool DHCP response
        Raw: { "huawei-ip-pool:global-pools": { "global-pool": [...] } }
        """
        pools: List[UnifiedDhcpPool] = []
        
        pools_root = (
            raw.get("huawei-ip-pool:global-pools") 
            or raw.get("global-pools") 
            or raw
        )
        pool_list = pools_root.get("global-pool", [])
        
        if not isinstance(pool_list, list):
            pool_list = [pool_list]
        
        for p in pool_list:
            if not isinstance(p, dict):
                continue
            
            pool_name = p.get("pool-name", "")
            
            # Gateway & mask
            gw = p.get("gateway", {})
            gateway = gw.get("ip-address") if isinstance(gw, dict) else None
            mask = gw.get("mask") if isinstance(gw, dict) else None
            
            # IP range (sections)
            start_ip = None
            end_ip = None
            sections = p.get("section", [])
            if not isinstance(sections, list):
                sections = [sections]
            if sections and isinstance(sections[0], dict):
                start_ip = sections[0].get("start-ip-address")
                end_ip = sections[0].get("end-ip-address")
            
            # DNS
            dns_servers = []
            dns_list = p.get("dns-list", {}).get("dns", [])
            if not isinstance(dns_list, list):
                dns_list = [dns_list]
            for d in dns_list:
                if isinstance(d, dict):
                    addr = d.get("ip-address")
                    if addr:
                        dns_servers.append(addr)
            
            # Lease
            lease_days = None
            lease = p.get("lease", {})
            if isinstance(lease, dict):
                lease_days = lease.get("day")
            
            pools.append(UnifiedDhcpPool(
                pool_name=pool_name,
                gateway=gateway,
                subnet_mask=mask,
                start_ip=start_ip,
                end_ip=end_ip,
                dns_servers=dns_servers,
                lease_days=int(lease_days) if lease_days is not None else None,
            ))
        
        out = UnifiedDhcpPoolList(pools=pools, total_count=len(pools))
        return out.model_dump()
    
    # =========================================================
    # Cisco
    # =========================================================
    
    def _normalize_cisco_dhcp(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse Cisco IOS-XE DHCP pool response
        Raw: { "Cisco-IOS-XE-native:pool": [...] } or from native/ip/dhcp/pool
        """
        pools: List[UnifiedDhcpPool] = []
        
        pool_list = (
            raw.get("Cisco-IOS-XE-dhcp:pool", [])
            or raw.get("Cisco-IOS-XE-native:pool", [])
            or raw.get("pool", [])
        )
        
        if not isinstance(pool_list, list):
            pool_list = [pool_list]
        
        for p in pool_list:
            if not isinstance(p, dict):
                continue
            
            pool_name = p.get("id", "")
            
            # Network
            network = p.get("network", {})
            gateway = network.get("number") if isinstance(network, dict) else None
            mask = network.get("mask") if isinstance(network, dict) else None
            
            # Default router
            default_router = p.get("default-router", {})
            if isinstance(default_router, dict):
                dr_list = default_router.get("default-router-list", [])
                if dr_list and not gateway:
                    gateway = dr_list[0] if isinstance(dr_list, list) else dr_list
            
            # DNS
            dns_servers = []
            dns_config = p.get("dns-server", {})
            if isinstance(dns_config, dict):
                dns_list = dns_config.get("dns-server-list", [])
                if isinstance(dns_list, list):
                    dns_servers = [str(d) for d in dns_list]
            
            pools.append(UnifiedDhcpPool(
                pool_name=str(pool_name),
                gateway=gateway,
                subnet_mask=mask,
            ))
        
        out = UnifiedDhcpPoolList(pools=pools, total_count=len(pools))
        return out.model_dump()
