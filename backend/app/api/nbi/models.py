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
