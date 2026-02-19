"""
Unified Schemas - Response format เดียวกันสำหรับทุก vendor
Frontend ใช้ schema เหล่านี้โดยไม่ต้องรู้จัก vendor
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


# ===== INTERFACE SCHEMAS =====
class UnifiedInterfaceStatus(BaseModel):
    """Unified interface status for show.interface"""
    name: str
    admin: Optional[str] = None           # up | down
    oper: Optional[str] = None            # up | down
    ipv4: List[str] = []                  # ["10.0.0.1/24"]
    ipv6: List[str] = []                  # ["2001:db8::1/64"]
    mac_address: Optional[str] = None
    mtu: Optional[int] = None
    speed: Optional[str] = None           # "1Gbps"
    duplex: Optional[str] = None          # "full" | "half"
    description: Optional[str] = None
    last_change: Optional[str] = None
    in_octets: Optional[int] = None
    out_octets: Optional[int] = None
    in_errors: Optional[int] = None
    out_errors: Optional[int] = None
    vendor: Optional[str] = None


class UnifiedInterfaceList(BaseModel):
    """Unified interface list for show.interfaces"""
    interfaces: List[UnifiedInterfaceStatus] = []
    total_count: int = 0
    up_count: int = 0
    down_count: int = 0


# ===== INTERFACE CONFIG (Write Operations) =====
class InterfaceConfig(BaseModel):
    """
    Unified Interface Configuration Model
    ใช้เป็น input สำหรับ configure_interface()
    
    Attributes:
        name: Interface name (e.g., "GigabitEthernet1", "Ethernet1/0/3")
        ip: IPv4 address (e.g., "10.0.0.1")
        mask: Subnet mask in CIDR format (e.g., "24") or dotted decimal
        enabled: Administrative status (True = no shutdown)
        description: Interface description
        mtu: MTU size
    """
    name: str
    ip: Optional[str] = None
    mask: Optional[str] = None
    enabled: bool = True
    description: Optional[str] = None
    mtu: Optional[int] = None


# ===== ROUTING SCHEMAS =====
class UnifiedRoute(BaseModel):
    """Single route entry"""
    prefix: str                           # "10.0.0.0/24"
    next_hop: Optional[str] = None        # "192.168.1.1" or interface
    protocol: str = "static"              # static | connected | ospf | bgp
    metric: Optional[int] = None
    preference: Optional[int] = None      # administrative distance
    vrf: Optional[str] = None
    interface: Optional[str] = None
    active: bool = True


class UnifiedRoutingTable(BaseModel):
    """Unified routing table for show.ip_route"""
    routes: List[UnifiedRoute] = []
    total_count: int = 0
    vrf: Optional[str] = None
    vendor: Optional[str] = None


# ===== SYSTEM SCHEMAS =====
class UnifiedSystemInfo(BaseModel):
    """Unified system info for show.version"""
    hostname: str
    vendor: str                           # cisco | huawei
    model: Optional[str] = None
    serial_number: Optional[str] = None
    software_version: Optional[str] = None
    uptime: Optional[str] = None
    uptime_seconds: Optional[int] = None
    memory_total: Optional[int] = None    # bytes
    memory_used: Optional[int] = None
    cpu_usage: Optional[float] = None     # percentage


class RunningConfigInterface(BaseModel):
    """Interface entry in running config"""
    name: str                                     # "GigabitEthernet1"
    type: Optional[str] = None                    # "GigabitEthernet"
    ip_address: Optional[str] = None              # "10.0.0.1/24"
    enabled: Optional[bool] = None                # True = no shutdown
    description: Optional[str] = None
    mtu: Optional[int] = None


class RunningConfigRoute(BaseModel):
    """Static route entry in running config"""
    prefix: str                                   # "10.0.0.0/24"
    next_hop: Optional[str] = None
    protocol: str = "static"


class RunningConfigOspf(BaseModel):
    """OSPF configuration in running config"""
    process_id: Optional[int] = None
    router_id: Optional[str] = None
    networks: List[Dict[str, Any]] = []           # [{"interface": "Gi1", "area": 0}]
    passive_interfaces: List[str] = []


class RunningConfigSystem(BaseModel):
    """System services in running config"""
    hostname: Optional[str] = None
    domain_name: Optional[str] = None
    ntp_servers: List[str] = []
    dns_servers: List[str] = []
    banner: Optional[str] = None


class UnifiedRunningConfig(BaseModel):
    """Unified running config — structured for frontend dashboard"""
    hostname: Optional[str] = None
    version: Optional[str] = None
    vendor: Optional[str] = None
    interfaces: List[RunningConfigInterface] = []
    static_routes: List[RunningConfigRoute] = []
    ospf: Optional[RunningConfigOspf] = None
    system: Optional[RunningConfigSystem] = None
    raw_config: Optional[Dict[str, Any]] = None   # raw JSON สำรอง
    section: Optional[str] = None


# ===== VLAN SCHEMAS =====
class UnifiedVlan(BaseModel):
    """Single VLAN entry"""
    vlan_id: int
    name: Optional[str] = None
    status: str = "active"                # active | suspended
    ports: List[str] = []                 # assigned ports


class UnifiedVlanList(BaseModel):
    """VLAN list"""
    vlans: List[UnifiedVlan] = []
    total_count: int = 0


# ===== GENERIC RESPONSE =====
class UnifiedConfigResult(BaseModel):
    """Generic config change result"""
    success: bool
    message: str = "Configuration applied"
    changes: List[str] = []               # list of changes made
    warnings: List[str] = []


# ===== Helper function =====
def create_success_result(message: str = "OK", changes: List[str] = None) -> Dict[str, Any]:
    """Create a success result dict"""
    return UnifiedConfigResult(
        success=True,
        message=message,
        changes=changes or []
    ).model_dump()
