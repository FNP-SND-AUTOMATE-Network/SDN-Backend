from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class OsType(str, Enum):
    CISCO_IOS = "CISCO_IOS"
    CISCO_NXOS = "CISCO_NXOS"
    CISCO_ASA = "CISCO_ASA"
    CISCO_Nexus = "CISCO_Nexus"
    CISCO_IOS_XR = "CISCO_IOS_XR"
    CISCO_IOS_XE = "CISCO_IOS_XE"
    HUAWEI_VRP = "HUAWEI_VRP"
    OTHER = "OTHER"

class OperatingSystemBase(BaseModel):
    os_type: OsType = Field(default=OsType.OTHER, description="ประเภทของ OS")
    description: Optional[str] = Field(None, description="คำอธิบาย OS", max_length=500)

class OperatingSystemCreate(OperatingSystemBase):
    pass

class OperatingSystemUpdate(BaseModel):
    os_type: Optional[OsType] = Field(None, description="ประเภทของ OS")
    description: Optional[str] = Field(None, description="คำอธิบาย OS", max_length=500)

class TagInfo(BaseModel):
    tag_id: str
    tag_name: str
    color: str
    type: str

    class Config:
        from_attributes = True

class OperatingSystemResponse(OperatingSystemBase):
    id: str = Field(..., description="ID ของ OS")
    created_at: datetime
    updated_at: datetime
    
    tags: list[TagInfo] = Field(default_factory=list, description="Tags ที่เชื่อมโยง")
    
    device_count: Optional[int] = Field(0, description="จำนวน Device ที่ใช้ OS นี้")
    backup_count: Optional[int] = Field(0, description="จำนวน Backup ที่เชื่อมโยง")
    total_usage: Optional[int] = Field(0, description="จำนวนการใช้งานทั้งหมด")

    class Config:
        from_attributes = True

class OperatingSystemListResponse(BaseModel):
    total: int = Field(..., description="จำนวนทั้งหมด")
    page: int = Field(..., description="หน้าปัจจุบัน")
    page_size: int = Field(..., description="ขนาดหน้า")
    operating_systems: list[OperatingSystemResponse] = Field(..., description="รายการ OS")

class OperatingSystemCreateResponse(BaseModel):
    message: str
    operating_system: OperatingSystemResponse

class OperatingSystemUpdateResponse(BaseModel):
    message: str
    operating_system: OperatingSystemResponse

class OperatingSystemDeleteResponse(BaseModel):
    message: str

class OperatingSystemUsageResponse(BaseModel):
    id: str
    os_type: str
    device_networks: list[dict] = Field(default_factory=list, description="รายการ Device ที่ใช้ OS นี้")
    backups: list[dict] = Field(default_factory=list, description="รายการ Backup ที่เชื่อมโยง")
    total_usage: int = Field(..., description="จำนวนการใช้งานทั้งหมด")

