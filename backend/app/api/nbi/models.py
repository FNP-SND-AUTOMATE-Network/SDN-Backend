"""
NBI Models
Error Codes, Request Models, Response Models
"""
from typing import Dict, List, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field, validator


# ===== Error Codes Enum =====

class ErrorCode(str, Enum):
    """Error codes สำหรับ Frontend"""
    # Success
    SUCCESS = "SUCCESS"
    
    # 400 Bad Request
    MISSING_NODE_ID = "MISSING_NODE_ID"
    MISSING_NETCONF_HOST = "MISSING_NETCONF_HOST"
    MISSING_NETCONF_CREDENTIALS = "MISSING_NETCONF_CREDENTIALS"
    INVALID_DEVICE_ID = "INVALID_DEVICE_ID"
    INVALID_INTENT = "INVALID_INTENT"
    INVALID_PARAMS = "INVALID_PARAMS"
    INVALID_VENDOR = "INVALID_VENDOR"
    
    # 404 Not Found
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    INTENT_NOT_FOUND = "INTENT_NOT_FOUND"
    NODE_NOT_FOUND_IN_ODL = "NODE_NOT_FOUND_IN_ODL"
    
    # 409 Conflict
    DEVICE_ALREADY_MOUNTED = "DEVICE_ALREADY_MOUNTED"
    DEVICE_NOT_MOUNTED = "DEVICE_NOT_MOUNTED"
    DEVICE_ALREADY_EXISTS = "DEVICE_ALREADY_EXISTS"
    
    # 502 Bad Gateway
    ODL_CONNECTION_FAILED = "ODL_CONNECTION_FAILED"
    ODL_REQUEST_FAILED = "ODL_REQUEST_FAILED"
    ODL_MOUNT_FAILED = "ODL_MOUNT_FAILED"
    ODL_UNMOUNT_FAILED = "ODL_UNMOUNT_FAILED"
    
    # 503 Service Unavailable
    ODL_NOT_AVAILABLE = "ODL_NOT_AVAILABLE"
    DATABASE_ERROR = "DATABASE_ERROR"
    
    # 504 Gateway Timeout
    ODL_TIMEOUT = "ODL_TIMEOUT"
    MOUNT_TIMEOUT = "MOUNT_TIMEOUT"
    
    # Device Status
    DEVICE_NOT_CONNECTED = "DEVICE_NOT_CONNECTED"
    DEVICE_CONNECTING = "DEVICE_CONNECTING"


# ===== Base Response Models =====

class APIResponse(BaseModel):
    """Base response สำหรับทุก API"""
    success: bool
    code: str  # ErrorCode enum value
    message: str
    data: Optional[Dict[str, Any]] = None


class MountRequest(BaseModel):
    """Request body สำหรับ mount device"""
    wait_for_connection: bool = Field(
        default=True, 
        description="รอจนกว่าจะ connected (max 30s)"
    )
    max_wait_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="เวลารอสูงสุด (วินาที) - 5 ถึง 120"
    )


class MountResponse(BaseModel):
    """Response สำหรับ mount operations"""
    success: bool
    code: str
    message: str
    node_id: Optional[str] = None
    connection_status: Optional[str] = None
    device_status: Optional[str] = None
    ready_for_intent: bool = False
    data: Optional[Dict[str, Any]] = None


class SyncResponse(BaseModel):
    """Response สำหรับ sync operations"""
    success: bool
    code: str
    message: str
    data: Optional[Dict[str, Any]] = None


class DeviceListResponse(BaseModel):
    """Response สำหรับ list devices"""
    success: bool
    code: str
    message: str
    devices: List[Dict[str, Any]]
    total: int
    source: str


class DeviceDetailResponse(BaseModel):
    """Response สำหรับ device detail"""
    success: bool
    code: str
    message: str
    device: Optional[Dict[str, Any]] = None


class IntentListResponse(BaseModel):
    """Response สำหรับ list intents"""
    success: bool
    code: str
    message: str
    intents: Dict[str, List[str]]
    intents_by_os: Optional[Dict[str, Any]] = None


class AutoCreateRequest(BaseModel):
    """Request body สำหรับ auto-create device จาก ODL"""
    node_id: str = Field(..., min_length=1, description="ODL node-id")
    vendor: str = Field(default="cisco", description="Vendor: cisco, huawei, juniper, arista")
    
    @validator('vendor')
    def validate_vendor(cls, v):
        valid_vendors = ['cisco', 'huawei', 'juniper', 'arista', 'other']
        if v.lower() not in valid_vendors:
            raise ValueError(f"Invalid vendor. Must be one of: {', '.join(valid_vendors)}")
        return v.lower()


class UpdateNetconfRequest(BaseModel):
    """Request body สำหรับ update NETCONF credentials"""
    netconf_host: Optional[str] = Field(None, description="IP/Hostname สำหรับ NETCONF")
    netconf_port: int = Field(default=830, description="NETCONF port")
    vendor: Optional[str] = Field(None, description="Vendor: cisco, huawei, juniper, arista")

class OdlConfigRequest(BaseModel):
    """Request body สำหรับแก้ไข ODL Config"""
    odl_base_url: str = Field(..., description="Base URL ของ OpenDaylight")
    odl_username: str = Field(..., description="Username สำหรับ ODL")
    odl_password: str = Field(..., description="Password สำหรับ ODL")
    odl_timeout_sec: float = Field(default=10.0, description="Timeout (วินาที)")
    odl_retry: int = Field(default=1, description="จำนวนครั้งที่ Retry")

class OdlConfigResponse(BaseModel):
    """Response สำหรับแบบ ODL Config"""
    success: bool
    message: str = "Success"
    data: Dict[str, Any]


# ===== OpenFlow Flow Management Models =====

class FlowAddRequest(BaseModel):
    """Request body สำหรับ Base Connectivity Flow (L1 Forwarding)"""
    flow_id: str = Field(..., min_length=1, description="ชื่อกฎ เช่น 'base-ovs1' (ถ้า bidirectional จะต่อท้าย -forward/-reverse ให้อัตโนมัติ)")
    node_id: str = Field(..., min_length=1, description="node_id ของ OpenFlow switch (เช่น 'openflow:1')")
    inbound_interface_id: str = Field(..., description="UUID ของ Interface ขาเข้า")
    outbound_interface_id: str = Field(..., description="UUID ของ Interface ขาออก")
    priority: int = Field(default=500, ge=0, le=65535, description="Priority ของ flow rule (0-65535)")
    table_id: int = Field(default=0, ge=0, le=255, description="Flow Table ID (default: 0)")
    bidirectional: bool = Field(default=True, description="สร้างทั้งขาไป (forward) และขากลับ (reverse) ใน 1 API call")


class FlowDeleteRequest(BaseModel):
    """Request body สำหรับลบ OpenFlow Flow Rule"""
    node_id: str = Field(..., min_length=1, description="node_id ของ OpenFlow switch")
    table_id: int = Field(default=0, ge=0, le=255, description="Flow Table ID")


class FlowResponse(BaseModel):
    """Response สำหรับ OpenFlow Flow operations"""
    success: bool
    code: str
    message: str
    data: Optional[Dict[str, Any]] = None


class TrafficSteerRequest(BaseModel):
    """Request body สำหรับ Traffic Steering Flow — redirect TCP traffic ไปทางอื่น"""
    flow_id: str = Field(..., min_length=1, description="ชื่อกฎ เช่น 'steer-tcp8080'")
    node_id: str = Field(..., min_length=1, description="node_id ของ switch (เช่น 'openflow:1')")
    inbound_interface_id: str = Field(..., description="UUID ของ Interface ขาเข้า (match in-port)")
    outbound_interface_id: str = Field(..., description="UUID ของ Interface ขาออก (redirect output)")
    tcp_dst_port: int = Field(..., ge=1, le=65535, description="TCP destination port ที่ต้องการ redirect (เช่น 8080)")
    priority: int = Field(default=600, ge=0, le=65535, description="Priority (ควรสูงกว่า base wiring)")
    table_id: int = Field(default=0, ge=0, le=255, description="Flow Table ID")
    bidirectional: bool = Field(default=True, description="สร้างทั้งขาไป + ขากลับ ใน 1 API call")


class AclMacDropRequest(BaseModel):
    """L2 ACL — Drop traffic จาก source MAC เฉพาะเครื่อง"""
    flow_id: str = Field(..., min_length=1, description="ชื่อกฎ เช่น 'acl-mac-drop'")
    node_id: str = Field(..., min_length=1, description="node_id ของ switch")
    src_mac: str = Field(..., min_length=11, description="Source MAC Address เช่น '00:50:79:66:68:05'")
    priority: int = Field(default=1100, ge=0, le=65535, description="Priority (สูงมากเพื่อ block)")
    table_id: int = Field(default=0, ge=0, le=255, description="Flow Table ID")


class AclIpBlacklistRequest(BaseModel):
    """L3 ACL — Drop traffic ระหว่าง source IP กับ destination IP"""
    flow_id: str = Field(..., min_length=1, description="ชื่อกฎ เช่น 'acl-ip-blacklist'")
    node_id: str = Field(..., min_length=1, description="node_id ของ switch")
    src_ip: str = Field(..., min_length=7, description="Source IP (CIDR) เช่น '192.168.50.5/32'")
    dst_ip: str = Field(..., min_length=7, description="Destination IP (CIDR) เช่น '192.168.50.4/32'")
    priority: int = Field(default=1100, ge=0, le=65535, description="Priority")
    table_id: int = Field(default=0, ge=0, le=255, description="Flow Table ID")


class AclPortDropRequest(BaseModel):
    """L4 ACL — Drop traffic ที่ไปหา TCP destination port"""
    flow_id: str = Field(..., min_length=1, description="ชื่อกฎ เช่น 'acl-port-8080-block'")
    node_id: str = Field(..., min_length=1, description="node_id ของ switch")
    tcp_dst_port: int = Field(..., ge=1, le=65535, description="TCP destination port เช่น 8080")
    priority: int = Field(default=1200, ge=0, le=65535, description="Priority (สูงสุดใน ACL)")
    table_id: int = Field(default=0, ge=0, le=255, description="Flow Table ID")


class AclWhitelistRequest(BaseModel):
    """Whitelist — อนุญาตเฉพาะ TCP port ที่กำหนด (action: NORMAL)"""
    flow_id: str = Field(..., min_length=1, description="ชื่อกฎ เช่น 'acl-permit-http'")
    node_id: str = Field(..., min_length=1, description="node_id ของ switch")
    tcp_dst_port: int = Field(..., ge=1, le=65535, description="TCP destination port ที่อนุญาต เช่น 80")
    priority: int = Field(default=1000, ge=0, le=65535, description="Priority (ต่ำกว่า drop เพื่อใช้คู่กับ drop-all)")
    table_id: int = Field(default=0, ge=0, le=255, description="Flow Table ID")


class ArpFloodRequest(BaseModel):
    """Request body สำหรับ ARP Flood Flow — กระจาย ARP ทุกพอร์ต"""
    flow_id: str = Field(..., min_length=1, description="ชื่อกฎ เช่น 'arp-flood-ovs1'")
    node_id: str = Field(..., min_length=1, description="node_id ของ switch (เช่น 'openflow:1')")
    priority: int = Field(default=400, ge=0, le=65535, description="Priority (ต่ำกว่า base wiring)")
    table_id: int = Field(default=0, ge=0, le=255, description="Flow Table ID")


class MacSteerRequest(BaseModel):
    """Request body สำหรับ L2 MAC-based Steering — redirect traffic จาก source MAC เฉพาะเครื่อง"""
    flow_id: str = Field(..., min_length=1, description="ชื่อกฎ เช่น 'steer-mac-ovs2'")
    node_id: str = Field(..., min_length=1, description="node_id ของ switch")
    src_mac: str = Field(..., min_length=11, description="Source MAC Address เช่น '00:50:79:66:68:05'")
    outbound_interface_id: str = Field(..., description="UUID ของ Interface ขาออก (redirect destination)")
    priority: int = Field(default=960, ge=0, le=65535, description="Priority (ควรสูง)")
    table_id: int = Field(default=0, ge=0, le=255, description="Flow Table ID")


class IpSteerRequest(BaseModel):
    """Request body สำหรับ L3 IP-based Steering — redirect traffic ไปหา destination IP"""
    flow_id: str = Field(..., min_length=1, description="ชื่อกฎ เช่น 'steer-ip-ovs2'")
    node_id: str = Field(..., min_length=1, description="node_id ของ switch")
    dst_ip: str = Field(..., min_length=7, description="Destination IP (CIDR) เช่น '192.168.50.4/32'")
    outbound_interface_id: str = Field(..., description="UUID ของ Interface ขาออก (redirect destination)")
    priority: int = Field(default=960, ge=0, le=65535, description="Priority (ควรสูง)")
    table_id: int = Field(default=0, ge=0, le=255, description="Flow Table ID")


# ========= Flow Rule DB Response (Dashboard) =========

class FlowRuleItem(BaseModel):
    """FlowRule record จาก DB — ใช้แสดง flow list บน Dashboard"""
    id: str
    flow_id: str
    node_id: str
    table_id: int
    flow_type: str
    priority: int
    bidirectional: bool
    pair_flow_id: Optional[str] = None
    direction: Optional[str] = None
    match_details: Optional[dict] = None
    status: str  # PENDING | ACTIVE | FAILED | DELETED
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FlowRuleListResponse(BaseModel):
    """Response สำหรับ GET /flow-rules"""
    success: bool
    code: str
    message: str
    data: List[FlowRuleItem] = []
    total: int = 0





