"""
Intent Registry - กำหนด Intents ทั้งหมดที่ระบบรองรับ
แบ่งเป็น namespace สำหรับจัดกลุ่ม operations
"""
from enum import Enum
from typing import Dict, List, Set
from dataclasses import dataclass, field


class IntentCategory(str, Enum):
    """หมวดหมู่ของ Intent"""
    INTERFACE = "interface"
    ROUTING = "routing"
    SYSTEM = "system"
    SHOW = "show"
    ACL = "acl"
    DEVICE = "device"  # Device management (mount/unmount)
    DHCP = "dhcp"      # DHCP server configuration
    FLOW = "flow"      # OpenFlow rules


@dataclass
class IntentDefinition:
    """คำจำกัดความของแต่ละ Intent"""
    name: str                           # ชื่อ intent เช่น "interface.set_ipv4"
    category: IntentCategory            # หมวดหมู่
    description: str                    # คำอธิบาย
    required_params: List[str]          # params ที่ต้องมี
    optional_params: List[str] = field(default_factory=list)  # params ทางเลือก
    is_read_only: bool = False          # True = GET operation (ไม่เปลี่ยน config)
    needs_normalization: bool = True    # True = ต้อง normalize response (Default True for Unified JSON)


class IntentRegistry:
    """
    Registry กลางสำหรับ Intent ทั้งหมด
    ใช้ validate และดึงข้อมูล intent
    """
    
    # ===== INTERFACE INTENTS =====
    INTERFACE_SET_IPV4 = IntentDefinition(
        name="interface.set_ipv4",
        category=IntentCategory.INTERFACE,
        description="Set IPv4 address on interface",
        required_params=["interface", "ip"],
        optional_params=["prefix", "mask", "description"],
    )
    
    INTERFACE_REMOVE_IPV4 = IntentDefinition(
        name="interface.remove_ipv4",
        category=IntentCategory.INTERFACE,
        description="Remove IPv4 address from interface",
        required_params=["interface"],
        optional_params=["ip"],
    )
    
    INTERFACE_SET_IPV6 = IntentDefinition(
        name="interface.set_ipv6",
        category=IntentCategory.INTERFACE,
        description="Set IPv6 address on interface",
        required_params=["interface", "ip"],
        optional_params=["prefix", "mask", "description"],
    )
    
    INTERFACE_REMOVE_IPV6 = IntentDefinition(
        name="interface.remove_ipv6",
        category=IntentCategory.INTERFACE,
        description="Remove IPv6 address from interface",
        required_params=["interface"],
        optional_params=["ip"],
    )
    
    INTERFACE_ENABLE = IntentDefinition(
        name="interface.enable",
        category=IntentCategory.INTERFACE,
        description="Enable (no shutdown) an interface",
        required_params=["interface"],
    )
    
    INTERFACE_DISABLE = IntentDefinition(
        name="interface.disable",
        category=IntentCategory.INTERFACE,
        description="Disable (shutdown) an interface",
        required_params=["interface"],
    )
    
    INTERFACE_SET_DESCRIPTION = IntentDefinition(
        name="interface.set_description",
        category=IntentCategory.INTERFACE,
        description="Set description on interface",
        required_params=["interface", "description"],
    )
    
    INTERFACE_SET_MTU = IntentDefinition(
        name="interface.set_mtu",
        category=IntentCategory.INTERFACE,
        description="Set MTU size on interface",
        required_params=["interface", "mtu"],
    )

    INTERFACE_CREATE_SUBINTERFACE = IntentDefinition(
        name="interface.create_subinterface",
        category=IntentCategory.INTERFACE,
        description="Create sub-interface with Dot1Q encapsulation",
        required_params=["interface", "vlan_id"],
        optional_params=["ip", "prefix", "description"],
    )
    
    # ===== SHOW INTENTS =====
    SHOW_INTERFACE = IntentDefinition(
        name="show.interface",
        category=IntentCategory.SHOW,
        description="Show single interface status",
        required_params=["interface"],
        is_read_only=True,
    )
    
    SHOW_INTERFACES = IntentDefinition(
        name="show.interfaces",
        category=IntentCategory.SHOW,
        description="Show all interfaces",
        required_params=[],
        is_read_only=True,
    )
    
    SHOW_RUNNING_CONFIG = IntentDefinition(
        name="show.running_config",
        category=IntentCategory.SHOW,
        description="Show running configuration",
        required_params=[],
        optional_params=["section"],
        is_read_only=True,
    )
    
    SHOW_VERSION = IntentDefinition(
        name="show.version",
        category=IntentCategory.SHOW,
        description="Show device version/system info",
        required_params=[],
        is_read_only=True,
    )
    
    SHOW_IP_ROUTE = IntentDefinition(
        name="show.ip_route",
        category=IntentCategory.SHOW,
        description="Show IP routing table",
        required_params=[],
        optional_params=["vrf"],
        is_read_only=True,
    )
    
    SHOW_IP_INTERFACE_BRIEF = IntentDefinition(
        name="show.ip_interface_brief",
        category=IntentCategory.SHOW,
        description="Show IP interface brief (summary)",
        required_params=[],
        is_read_only=True,
    )
    
    # ===== ROUTING INTENTS =====
    ROUTING_STATIC_ADD = IntentDefinition(
        name="routing.static.add",
        category=IntentCategory.ROUTING,
        description="Add static route",
        required_params=["prefix", "next_hop"],
        optional_params=["metric", "vrf", "description", "mask"],
    )
    
    ROUTING_STATIC_DELETE = IntentDefinition(
        name="routing.static.delete",
        category=IntentCategory.ROUTING,
        description="Delete static route",
        required_params=["prefix"],
        optional_params=["vrf", "mask", "next_hop"],
    )
    
    ROUTING_DEFAULT_ADD = IntentDefinition(
        name="routing.default.add",
        category=IntentCategory.ROUTING,
        description="Add default route (0.0.0.0/0)",
        required_params=["next_hop"],
        optional_params=["metric", "vrf"],
    )
    
    ROUTING_DEFAULT_DELETE = IntentDefinition(
        name="routing.default.delete",
        category=IntentCategory.ROUTING,
        description="Delete default route",
        required_params=[],
        optional_params=["vrf"],
    )
    
    # ===== OSPF INTENTS =====
    ROUTING_OSPF_ENABLE = IntentDefinition(
        name="routing.ospf.enable",
        category=IntentCategory.ROUTING,
        description="Enable OSPF process",
        required_params=["process_id"],
        optional_params=["router_id"],
    )
    
    ROUTING_OSPF_DISABLE = IntentDefinition(
        name="routing.ospf.disable",
        category=IntentCategory.ROUTING,
        description="Disable/Remove OSPF process",
        required_params=["process_id"],
    )
    
    ROUTING_OSPF_ADD_NETWORK = IntentDefinition(
        name="routing.ospf.add_network",
        category=IntentCategory.ROUTING,
        description="Add OSPF network (network <ip> <wildcard> area <area>)",
        required_params=["process_id", "area", "network", "wildcard_mask"],
    )
    
    ROUTING_OSPF_ADD_NETWORK_INTERFACE = IntentDefinition(
        name="routing.ospf.add_network_interface",
        category=IntentCategory.ROUTING,
        description="Add OSPF to interface (ip ospf process-id area area-id)",
        required_params=["process_id", "interface", "area"],
    )
    
    ROUTING_OSPF_REMOVE_NETWORK_INTERFACE = IntentDefinition(
        name="routing.ospf.remove_network_interface",
        category=IntentCategory.ROUTING,
        description="Remove OSPF from interface",
        required_params=["process_id", "interface"],
    )
    
    ROUTING_OSPF_SET_ROUTER_ID = IntentDefinition(
        name="routing.ospf.set_router_id",
        category=IntentCategory.ROUTING,
        description="Set OSPF router ID",
        required_params=["process_id", "router_id"],
    )
    
    ROUTING_OSPF_SET_PASSIVE_INTERFACE = IntentDefinition(
        name="routing.ospf.set_passive_interface",
        category=IntentCategory.ROUTING,
        description="Set interface as passive (no OSPF hello)",
        required_params=["process_id", "interface"],
    )
    
    ROUTING_OSPF_REMOVE_PASSIVE_INTERFACE = IntentDefinition(
        name="routing.ospf.remove_passive_interface",
        category=IntentCategory.ROUTING,
        description="Remove passive interface setting",
        required_params=["process_id", "interface"],
    )
    
    SHOW_OSPF_NEIGHBORS = IntentDefinition(
        name="show.ospf.neighbors",
        category=IntentCategory.SHOW,
        description="Show OSPF neighbor adjacencies",
        required_params=[],
        optional_params=["process_id"],
        is_read_only=True,
    )
    
    SHOW_OSPF_DATABASE = IntentDefinition(
        name="show.ospf.database",
        category=IntentCategory.SHOW,
        description="Show OSPF link-state database",
        required_params=[],
        optional_params=["process_id", "area"],
        is_read_only=True,
    )
    
    # ===== SYSTEM INTENTS =====
    SYSTEM_SET_HOSTNAME = IntentDefinition(
        name="system.set_hostname",
        category=IntentCategory.SYSTEM,
        description="Set device hostname",
        required_params=["hostname"],
    )
    
    SYSTEM_SET_BANNER = IntentDefinition(
        name="system.set_banner",
        category=IntentCategory.SYSTEM,
        description="Set login banner",
        required_params=["banner"],
        optional_params=["banner_type"],
    )
    
    SYSTEM_SET_NTP = IntentDefinition(
        name="system.set_ntp",
        category=IntentCategory.SYSTEM,
        description="Configure NTP server",
        required_params=["server"],
        optional_params=["prefer"],
    )
    
    SYSTEM_SET_DNS = IntentDefinition(
        name="system.set_dns",
        category=IntentCategory.SYSTEM,
        description="Configure DNS server",
        required_params=["server"],
        optional_params=["domain"],
    )
    
    SYSTEM_SAVE_CONFIG = IntentDefinition(
        name="system.save_config",
        category=IntentCategory.SYSTEM,
        description="Save running config to startup",
        required_params=[],
    )
    
    # ===== DEVICE MANAGEMENT INTENTS =====
    # Note: device.mount and device.unmount removed - use dedicated REST endpoints:
    #   POST /api/v1/nbi/devices/{node_id}/mount
    #   DELETE /api/v1/nbi/devices/{node_id}/mount
    
    DEVICE_STATUS = IntentDefinition(
        name="device.status",
        category=IntentCategory.DEVICE,
        description="Get NETCONF device connection status",
        required_params=[],
        is_read_only=True,
    )
    
    DEVICE_LIST = IntentDefinition(
        name="device.list",
        category=IntentCategory.DEVICE,
        description="List all mounted NETCONF devices",
        required_params=[],
        is_read_only=True,
    )
    
    
    # ===== DHCP INTENTS =====
    DHCP_CREATE_POOL = IntentDefinition(
        name="dhcp.create_pool",
        category=IntentCategory.DHCP,
        description="Create DHCP pool",
        required_params=["pool_name", "gateway", "mask", "start_ip", "end_ip"],
        optional_params=["dns_servers", "lease_days"],
    )
    
    DHCP_DELETE_POOL = IntentDefinition(
        name="dhcp.delete_pool",
        category=IntentCategory.DHCP,
        description="Delete DHCP pool",
        required_params=["pool_name"],
    )
    
    DHCP_UPDATE_POOL = IntentDefinition(
        name="dhcp.update_pool",
        category=IntentCategory.DHCP,
        description="Update DHCP pool",
        required_params=["pool_name"],
        optional_params=["gateway", "mask", "start_ip", "end_ip", "dns_servers"],
    )
    
    SHOW_DHCP_POOLS = IntentDefinition(
        name="show.dhcp_pools",
        category=IntentCategory.SHOW,
        description="Show DHCP pools",
        required_params=[],
        is_read_only=True,
    )
    
    # ===== FLOW INTENTS (OpenFlow) =====
    FLOW_ADD = IntentDefinition(
        name="flow.add",
        category=IntentCategory.FLOW,
        description="Add an OpenFlow rule",
        required_params=["table_id", "flow_id", "priority", "match", "instructions"],
    )

    FLOW_DELETE = IntentDefinition(
        name="flow.delete",
        category=IntentCategory.FLOW,
        description="Delete an OpenFlow rule",
        required_params=["table_id", "flow_id"],
    )
    
    SHOW_FLOWS = IntentDefinition(
        name="show.flows",
        category=IntentCategory.SHOW,
        description="Show OpenFlow rules",
        required_params=[],
        optional_params=["table_id"],
        is_read_only=True,
    )

    # ===== Registry Map =====
    _registry: Dict[str, IntentDefinition] = {}
    
    @classmethod
    def _build_registry(cls) -> Dict[str, IntentDefinition]:
        """Build registry map from class attributes"""
        if cls._registry:
            return cls._registry
            
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if isinstance(attr, IntentDefinition):
                cls._registry[attr.name] = attr
        return cls._registry
    
    @classmethod
    def get(cls, intent_name: str) -> IntentDefinition | None:
        """Get intent definition by name"""
        registry = cls._build_registry()
        return registry.get(intent_name)
    
    @classmethod
    def exists(cls, intent_name: str) -> bool:
        """Check if intent exists"""
        return cls.get(intent_name) is not None
    
    @classmethod
    def all_intents(cls) -> List[IntentDefinition]:
        """Get all registered intents"""
        return list(cls._build_registry().values())
    
    @classmethod
    def by_category(cls, category: IntentCategory) -> List[IntentDefinition]:
        """Get intents by category"""
        return [i for i in cls.all_intents() if i.category == category]
    
    @classmethod
    def validate_params(cls, intent_name: str, params: Dict) -> List[str]:
        """
        Validate params for intent
        Returns list of missing required params
        """
        intent = cls.get(intent_name)
        if not intent:
            return [f"Unknown intent: {intent_name}"]
        
        missing = []
        for req in intent.required_params:
            if req not in params or params[req] is None:
                missing.append(req)
        return missing
    
    @classmethod
    def get_supported_intents(cls) -> Dict[str, List[str]]:
        """Get all supported intents grouped by category"""
        result = {}
        for intent in cls.all_intents():
            cat = intent.category.value
            if cat not in result:
                result[cat] = []
            result[cat].append(intent.name)
        return result


# ===== Intent Names Constants (for type safety) =====
class Intents:
    """
    Intent name constants for type-safe usage
    Usage: Intents.INTERFACE.SET_IPV4
    """
    class INTERFACE:
        SET_IPV4 = "interface.set_ipv4"
        REMOVE_IPV4 = "interface.remove_ipv4"
        SET_IPV6 = "interface.set_ipv6"
        REMOVE_IPV6 = "interface.remove_ipv6"
        ENABLE = "interface.enable"
        DISABLE = "interface.disable"
        SET_DESCRIPTION = "interface.set_description"
        SET_MTU = "interface.set_mtu"
        CREATE_SUBINTERFACE = "interface.create_subinterface"
    
    class SHOW:
        INTERFACE = "show.interface"
        INTERFACES = "show.interfaces"
        RUNNING_CONFIG = "show.running_config"
        VERSION = "show.version"
        IP_ROUTE = "show.ip_route"
        IP_INTERFACE_BRIEF = "show.ip_interface_brief"
        # OSPF
        OSPF_NEIGHBORS = "show.ospf.neighbors"
        OSPF_DATABASE = "show.ospf.database"
        # DHCP
        DHCP_POOLS = "show.dhcp_pools"
        # OpenFlow
        FLOWS = "show.flows"
    
    class ROUTING:
        STATIC_ADD = "routing.static.add"
        STATIC_DELETE = "routing.static.delete"
        DEFAULT_ADD = "routing.default.add"
        DEFAULT_DELETE = "routing.default.delete"
        # OSPF
        OSPF_ENABLE = "routing.ospf.enable"
        OSPF_DISABLE = "routing.ospf.disable"
        OSPF_ADD_NETWORK = "routing.ospf.add_network"
        OSPF_ADD_NETWORK_INTERFACE = "routing.ospf.add_network_interface"
        OSPF_REMOVE_NETWORK_INTERFACE = "routing.ospf.remove_network_interface"
        OSPF_SET_ROUTER_ID = "routing.ospf.set_router_id"
        OSPF_SET_PASSIVE_INTERFACE = "routing.ospf.set_passive_interface"
        OSPF_REMOVE_PASSIVE_INTERFACE = "routing.ospf.remove_passive_interface"
    
    class SYSTEM:
        SET_HOSTNAME = "system.set_hostname"
        SET_BANNER = "system.set_banner"
        SET_NTP = "system.set_ntp"
        SET_DNS = "system.set_dns"
        SAVE_CONFIG = "system.save_config"
    
    class DEVICE:
        # Note: MOUNT and UNMOUNT removed - use dedicated REST endpoints
        STATUS = "device.status"
        LIST = "device.list"
    
    
    class DHCP:
        CREATE_POOL = "dhcp.create_pool"
        DELETE_POOL = "dhcp.delete_pool"
        UPDATE_POOL = "dhcp.update_pool"

    class FLOW:
        ADD = "flow.add"
        DELETE = "flow.delete"
