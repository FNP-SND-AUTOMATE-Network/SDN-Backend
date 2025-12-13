from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from enum import Enum
import re

class TypeTag(str, Enum):
    """ประเภทของ Tag"""
    TAG = "tag"
    GROUP = "group"
    OTHER = "other"

class TagBase(BaseModel):
    """Base model สำหรับ Tag"""
    tag_name: str = Field(..., description="ชื่อ Tag (ต้องไม่ซ้ำ)", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="คำอธิบาย Tag", max_length=500)
    type: TypeTag = Field(TypeTag.OTHER, description="ประเภทของ Tag (tag/group/other)")
    color: str = Field("#3B82F6", description="สีของ Tag (Hex color code)", pattern="^#[0-9A-Fa-f]{6}$")
    
    @field_validator('color')
    @classmethod
    def validate_color(cls, v: str) -> str:
        """ตรวจสอบ hex color format"""
        if not re.match(r'^#[0-9A-Fa-f]{6}$', v):
            raise ValueError('สีต้องอยู่ในรูปแบบ hex color code (#RRGGBB) เช่น #3B82F6')
        return v.upper()  # แปลงเป็นตัวพิมพ์ใหญ่

class TagCreate(TagBase):
    """Model สำหรับสร้าง Tag ใหม่"""
    pass

class TagUpdate(BaseModel):
    """Model สำหรับอัปเดต Tag"""
    tag_name: Optional[str] = Field(None, description="ชื่อ Tag (ต้องไม่ซ้ำ)", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="คำอธิบาย Tag", max_length=500)
    type: Optional[TypeTag] = Field(None, description="ประเภทของ Tag (tag/group/other)")
    color: Optional[str] = Field(None, description="สีของ Tag (Hex color code)", pattern="^#[0-9A-Fa-f]{6}$")
    
    @field_validator('color')
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        """ตรวจสอบ hex color format"""
        if v is None:
            return v
        if not re.match(r'^#[0-9A-Fa-f]{6}$', v):
            raise ValueError('สีต้องอยู่ในรูปแบบ hex color code (#RRGGBB) เช่น #3B82F6')
        return v.upper()  # แปลงเป็นตัวพิมพ์ใหญ่

class TagResponse(TagBase):
    """Model สำหรับ response ของ Tag"""
    tag_id: str = Field(..., description="ID ของ Tag")
    created_at: datetime
    updated_at: datetime
    
    # นับจำนวนการใช้งาน
    device_count: Optional[int] = Field(0, description="จำนวน Device ที่ใช้ Tag นี้")
    os_count: Optional[int] = Field(0, description="จำนวน OS ที่ใช้ Tag นี้")
    template_count: Optional[int] = Field(0, description="จำนวน Template ที่ใช้ Tag นี้")
    total_usage: Optional[int] = Field(0, description="จำนวนการใช้งานทั้งหมด")

    class Config:
        from_attributes = True

class TagListResponse(BaseModel):
    """Model สำหรับ response ของรายการ Tag"""
    total: int = Field(..., description="จำนวนทั้งหมด")
    page: int = Field(..., description="หน้าปัจจุบัน")
    page_size: int = Field(..., description="ขนาดหน้า")
    tags: list[TagResponse] = Field(..., description="รายการ Tag")

class TagCreateResponse(BaseModel):
    """Model สำหรับ response เมื่อสร้าง Tag สำเร็จ"""
    message: str
    tag: TagResponse

class TagUpdateResponse(BaseModel):
    """Model สำหรับ response เมื่ออัปเดต Tag สำเร็จ"""
    message: str
    tag: TagResponse

class TagDeleteResponse(BaseModel):
    """Model สำหรับ response เมื่อลบ Tag สำเร็จ"""
    message: str

class TagUsageResponse(BaseModel):
    """Model สำหรับแสดงการใช้งาน Tag"""
    tag_id: str
    tag_name: str
    device_networks: list[dict] = Field(default_factory=list, description="รายการ Device ที่ใช้ Tag")
    operating_systems: list[dict] = Field(default_factory=list, description="รายการ OS ที่ใช้ Tag")
    configuration_templates: list[dict] = Field(default_factory=list, description="รายการ Template ที่ใช้ Tag")
    total_usage: int = Field(..., description="จำนวนการใช้งานทั้งหมด")

