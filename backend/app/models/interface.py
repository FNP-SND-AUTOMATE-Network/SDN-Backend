from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class InterfaceStatus(str, Enum):
    """สถานะของ Interface"""
    UP = "UP"
    DOWN = "DOWN"
    ADMIN_DOWN = "ADMIN_DOWN"
    TESTING = "TESTING"
    OTHER = "OTHER"

class InterfaceType(str, Enum):
    """ประเภทของ Interface"""
    PHYSICAL = "PHYSICAL"
    VIRTUAL = "VIRTUAL"
    LOOPBACK = "LOOPBACK"
    VLAN = "VLAN"
    TUNNEL = "TUNNEL"
    OTHER = "OTHER"

class InterfaceBase(BaseModel):
    """Base model สำหรับ Interface"""
    name: str = Field(..., description="ชื่อ Interface (เช่น GigabitEthernet0/1, eth0)", min_length=1, max_length=100)
    device_id: str = Field(..., description="Device Network ID ที่เชื่อมโยง")
    label: Optional[str] = Field(None, description="ชื่อย่อหรือป้ายกำกับ", max_length=200)
    status: InterfaceStatus = Field(default=InterfaceStatus.DOWN, description="สถานะของ Interface")
    type: InterfaceType = Field(default=InterfaceType.PHYSICAL, description="ประเภทของ Interface")
    description: Optional[str] = Field(None, description="คำอธิบาย Interface", max_length=1000)

class InterfaceCreate(InterfaceBase):
    """Model สำหรับสร้าง Interface ใหม่"""
    pass

class InterfaceUpdate(BaseModel):
    """Model สำหรับอัปเดต Interface"""
    name: Optional[str] = Field(None, description="ชื่อ Interface", min_length=1, max_length=100)
    label: Optional[str] = Field(None, description="ชื่อย่อหรือป้ายกำกับ", max_length=200)
    status: Optional[InterfaceStatus] = Field(None, description="สถานะของ Interface")
    type: Optional[InterfaceType] = Field(None, description="ประเภทของ Interface")
    description: Optional[str] = Field(None, description="คำอธิบาย Interface", max_length=1000)

class RelatedDeviceInfo(BaseModel):
    """ข้อมูล Device แบบย่อ"""
    id: str
    device_name: str
    device_model: str
    serial_number: str
    type: str

class InterfaceResponse(BaseModel):
    """Model สำหรับ response ของ Interface"""
    id: str = Field(..., description="ID ของ Interface")
    name: str
    device_id: str
    label: Optional[str]
    status: InterfaceStatus
    type: InterfaceType
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    # Related Info
    device: Optional[RelatedDeviceInfo] = None

    class Config:
        from_attributes = True

class InterfaceListResponse(BaseModel):
    """Model สำหรับ response ของรายการ Interface"""
    total: int = Field(..., description="จำนวนทั้งหมด")
    page: int = Field(..., description="หน้าปัจจุบัน")
    page_size: int = Field(..., description="ขนาดหน้า")
    interfaces: list[InterfaceResponse] = Field(..., description="รายการ Interface")

class InterfaceCreateResponse(BaseModel):
    """Model สำหรับ response เมื่อสร้าง Interface สำเร็จ"""
    message: str
    interface: InterfaceResponse

class InterfaceUpdateResponse(BaseModel):
    """Model สำหรับ response เมื่ออัปเดต Interface สำเร็จ"""
    message: str
    interface: InterfaceResponse

class InterfaceDeleteResponse(BaseModel):
    """Model สำหรับ response เมื่อลบ Interface สำเร็จ"""
    message: str

