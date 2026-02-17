from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum
import re 

# node_id validation pattern (URL-safe: a-z, A-Z, 0-9, -, _)
NODE_ID_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$')


def validate_node_id(value: str) -> str:
    """
    Validate node_id format:
    - ต้องขึ้นต้นด้วยตัวอักษรหรือตัวเลข
    - ประกอบด้วย a-z, A-Z, 0-9, -, _ เท่านั้น
    - ความยาว 1-63 ตัวอักษร
    - ไม่มี space หรือ special characters
    """
    if not value:
        raise ValueError('node_id is required')
    
    value = value.strip()
    
    if not NODE_ID_PATTERN.match(value):
        raise ValueError(
            'node_id must be 1-63 characters, start with alphanumeric, '
            'and contain only letters, numbers, hyphens (-), or underscores (_). '
            'No spaces or special characters allowed. Example: CSR1, router-core-01, SW_FLOOR3'
        )
    
    return value

class TypeDevice(str, Enum):
    SWITCH = "SWITCH"
    ROUTER = "ROUTER"
    FIREWALL = "FIREWALL"
    ACCESS_POINT = "ACCESS_POINT"
    OTHER = "OTHER"

class StatusDevice(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"
    OTHER = "OTHER"

# ========= NBI/ODL Enums =========
class DeviceVendor(str, Enum):
    """Vendor สำหรับเลือก driver ใน NBI"""
    CISCO = "CISCO"
    HUAWEI = "HUAWEI"
    JUNIPER = "JUNIPER"
    ARISTA = "ARISTA"
    OTHER = "OTHER"



class DeviceNetworkBase(BaseModel):
    serial_number: str = Field(..., description="Serial Number (ต้องไม่ซ้ำ)", min_length=1, max_length=100)
    device_name: str = Field(..., description="ชื่ออุปกรณ์", min_length=1, max_length=200)
    device_model: str = Field(..., description="รุ่นอุปกรณ์", min_length=1, max_length=200)
    type: TypeDevice = Field(default=TypeDevice.SWITCH, description="ประเภทอุปกรณ์")
    status: StatusDevice = Field(default=StatusDevice.OFFLINE, description="สถานะอุปกรณ์")
    ip_address: Optional[str] = Field(None, description="IP Address (สามารถเว้นว่างได้)", max_length=50)
    mac_address: str = Field(..., description="MAC Address (ต้องไม่ซ้ำ)", min_length=1, max_length=50)
    description: Optional[str] = Field(None, description="คำอธิบายอุปกรณ์", max_length=1000)
    
    # Foreign Keys
    policy_id: Optional[str] = Field(None, description="Policy ID")
    os_id: Optional[str] = Field(None, description="Operating System ID")
    backup_id: Optional[str] = Field(None, description="Backup ID")
    local_site_id: Optional[str] = Field(None, description="Local Site ID")
    configuration_template_id: Optional[str] = Field(None, description="Configuration Template ID")
    
    # NBI/ODL Fields - node_id is REQUIRED
    node_id: str = Field(
        ..., 
        description="ODL node-id (unique, URL-safe). ใช้เป็น path parameter ใน API. ตัวอย่าง: CSR1, router-core-01",
        min_length=1,
        max_length=63
    )
    vendor: DeviceVendor = Field(default=DeviceVendor.OTHER, description="Vendor สำหรับเลือก driver")
    
    # NETCONF Connection Fields (สำหรับ Mount)
    netconf_host: Optional[str] = Field(None, description="IP/Hostname สำหรับ NETCONF connection")
    netconf_port: int = Field(default=830, description="NETCONF port (default: 830, SSH)")
    netconf_username: Optional[str] = Field(None, description="Username สำหรับ NETCONF")
    netconf_password: Optional[str] = Field(None, description="Password สำหรับ NETCONF")
    
    @field_validator('node_id')
    @classmethod
    def validate_node_id_format(cls, v):
        return validate_node_id(v)

class DeviceNetworkCreate(DeviceNetworkBase):
    pass

class DeviceNetworkUpdate(BaseModel):
    serial_number: Optional[str] = Field(None, description="Serial Number (ต้องไม่ซ้ำ)", min_length=1, max_length=100)
    device_name: Optional[str] = Field(None, description="ชื่ออุปกรณ์", min_length=1, max_length=200)
    device_model: Optional[str] = Field(None, description="รุ่นอุปกรณ์", min_length=1, max_length=200)
    type: Optional[TypeDevice] = Field(None, description="ประเภทอุปกรณ์")
    status: Optional[StatusDevice] = Field(None, description="สถานะอุปกรณ์")
    ip_address: Optional[str] = Field(None, description="IP Address (สามารถเว้นว่างได้)", max_length=50)
    mac_address: Optional[str] = Field(None, description="MAC Address (ต้องไม่ซ้ำ)", min_length=1, max_length=50)
    description: Optional[str] = Field(None, description="คำอธิบายอุปกรณ์", max_length=1000)
    
    # Foreign Keys
    policy_id: Optional[str] = Field(None, description="Policy ID")
    os_id: Optional[str] = Field(None, description="Operating System ID")
    backup_id: Optional[str] = Field(None, description="Backup ID")
    tag_id: Optional[str] = Field(None, description="Tag ID")
    local_site_id: Optional[str] = Field(None, description="Local Site ID")
    configuration_template_id: Optional[str] = Field(None, description="Configuration Template ID")
    
    # NBI/ODL Fields
    node_id: Optional[str] = Field(None, description="ODL node-id สำหรับ topology-netconf", max_length=63)
    vendor: Optional[DeviceVendor] = Field(None, description="Vendor สำหรับเลือก driver")
    
    # NETCONF Connection Fields
    netconf_host: Optional[str] = Field(None, description="IP/Hostname สำหรับ NETCONF connection")
    netconf_port: Optional[int] = Field(None, description="NETCONF port")
    netconf_username: Optional[str] = Field(None, description="Username สำหรับ NETCONF")
    netconf_password: Optional[str] = Field(None, description="Password สำหรับ NETCONF")
    
    @field_validator('node_id')
    @classmethod
    def validate_node_id_format_update(cls, v):
        """Validate node_id format for update (allow None)"""
        if v is None:
            return v
        return validate_node_id(v)

# Related Info Models
class RelatedTagInfo(BaseModel):
    tag_id: str
    tag_name: str
    color: str
    type: str

class RelatedOSInfo(BaseModel):
    id: str
    os_name: str
    os_type: str

class RelatedSiteInfo(BaseModel):
    id: str
    site_code: str
    site_name: Optional[str]

class RelatedPolicyInfo(BaseModel):
    id: str
    policy_name: str

class RelatedBackupInfo(BaseModel):
    id: str
    backup_name: str
    status: str

class RelatedTemplateInfo(BaseModel):
    id: str
    template_name: str
    template_type: str

class DeviceNetworkResponse(BaseModel):
    """Response model สำหรับ Device Network (ไม่ inherit จาก Base เพื่อให้ node_id optional)"""
    id: str = Field(..., description="ID ของอุปกรณ์")
    serial_number: str
    device_name: str
    device_model: str
    type: str
    status: str
    ip_address: Optional[str] = None
    mac_address: str
    description: Optional[str] = None
    
    # Foreign Keys
    policy_id: Optional[str] = None
    os_id: Optional[str] = None
    backup_id: Optional[str] = None
    local_site_id: Optional[str] = None
    configuration_template_id: Optional[str] = None
    
    # NBI/ODL Fields - node_id is OPTIONAL in response (for backward compatibility)
    node_id: Optional[str] = Field(None, description="ODL node-id (unique, URL-safe)")
    vendor: Optional[str] = Field(None, description="Vendor สำหรับเลือก driver")
    
    # NETCONF Connection Fields
    netconf_host: Optional[str] = Field(None, description="IP/Hostname สำหรับ NETCONF")
    netconf_port: int = Field(default=830, description="NETCONF port")
    netconf_username: Optional[str] = Field(None, description="Username สำหรับ NETCONF")
    netconf_password: Optional[str] = Field(None, description="Password - will be null for security")
    
    created_at: datetime
    updated_at: datetime
    
    # NBI/ODL Status Fields
    odl_mounted: bool = Field(default=False, description="Mount status ใน ODL")
    odl_connection_status: Optional[str] = Field(None, description="ODL connection status")
    last_synced_at: Optional[datetime] = Field(None, description="Last sync time from ODL")
    ready_for_intent: bool = Field(default=False, description="พร้อมใช้งาน Intent API หรือไม่")
    
    tags: list[RelatedTagInfo] = Field(default_factory=list, description="Tags ที่เชื่อมโยง")
    operatingSystem: Optional[RelatedOSInfo] = None
    localSite: Optional[RelatedSiteInfo] = None
    policy: Optional[RelatedPolicyInfo] = None
    backup: Optional[RelatedBackupInfo] = None
    configuration_template: Optional[RelatedTemplateInfo] = None

    class Config:
        from_attributes = True

class DeviceNetworkListResponse(BaseModel):
    total: int = Field(..., description="จำนวนทั้งหมด")
    page: int = Field(..., description="หน้าปัจจุบัน")
    page_size: int = Field(..., description="ขนาดหน้า")
    devices: list[DeviceNetworkResponse] = Field(..., description="รายการอุปกรณ์")

class DeviceNetworkCreateResponse(BaseModel):
    message: str
    device: DeviceNetworkResponse

class DeviceNetworkUpdateResponse(BaseModel):
    message: str
    device: DeviceNetworkResponse

class DeviceNetworkDeleteResponse(BaseModel):
    message: str


class DeviceTagAssignment(BaseModel):
    tag_ids: list[str] = Field(..., description="รายการ Tag IDs", min_length=1)


