from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

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

class DeviceNetworkBase(BaseModel):
    serial_number: str = Field(..., description="Serial Number (ต้องไม่ซ้ำ)", min_length=1, max_length=100)
    device_name: str = Field(..., description="ชื่ออุปกรณ์", min_length=1, max_length=200)
    device_model: str = Field(..., description="รุ่นอุปกรณ์", min_length=1, max_length=200)
    type: TypeDevice = Field(default=TypeDevice.SWITCH, description="ประเภทอุปกรณ์")
    status: StatusDevice = Field(default=StatusDevice.ONLINE, description="สถานะอุปกรณ์")
    ip_address: Optional[str] = Field(None, description="IP Address (สามารถเว้นว่างได้)", max_length=50)
    mac_address: str = Field(..., description="MAC Address (ต้องไม่ซ้ำ)", min_length=1, max_length=50)
    description: Optional[str] = Field(None, description="คำอธิบายอุปกรณ์", max_length=1000)
    
    # Foreign Keys
    policy_id: Optional[str] = Field(None, description="Policy ID")
    os_id: Optional[str] = Field(None, description="Operating System ID")
    backup_id: Optional[str] = Field(None, description="Backup ID")
    local_site_id: Optional[str] = Field(None, description="Local Site ID")
    configuration_template_id: Optional[str] = Field(None, description="Configuration Template ID")

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

class DeviceNetworkResponse(DeviceNetworkBase):
    id: str = Field(..., description="ID ของอุปกรณ์")
    created_at: datetime
    updated_at: datetime
    
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
    """Model สำหรับการเพิ่ม/ลบ Tags"""
    tag_ids: list[str] = Field(..., description="รายการ Tag IDs", min_length=1)


