from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class TemplateType(str, Enum):
    NETWORK = "NETWORK"
    SECURITY = "SECURITY"
    OTHER = "OTHER"

class ConfigurationTemplateBase(BaseModel):
    template_name: str = Field(..., description="ชื่อ Template (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Template", max_length=1000)
    template_type: TemplateType = Field(default=TemplateType.OTHER, description="ประเภทของ Template")
    tag_name: Optional[str] = Field(None, description="Tag name ที่เชื่อมโยง")

class ConfigurationTemplateCreate(ConfigurationTemplateBase):
    pass

class ConfigurationTemplateUpdate(BaseModel):
    template_name: Optional[str] = Field(None, description="ชื่อ Template (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Template", max_length=1000)
    template_type: Optional[TemplateType] = Field(None, description="ประเภทของ Template")
    tag_name: Optional[str] = Field(None, description="Tag name ที่เชื่อมโยง")

class RelatedTagInfoTemplate(BaseModel):
    tag_id: str
    tag_name: str
    color: str
    type: str

class ConfigurationTemplateResponse(ConfigurationTemplateBase):
    id: str = Field(..., description="ID ของ Template")
    created_at: datetime
    updated_at: datetime
    
    # Related Info
    tag: Optional[RelatedTagInfoTemplate] = None
    
    # นับจำนวนการใช้งาน
    device_count: Optional[int] = Field(0, description="จำนวน Device ที่ใช้ Template นี้")

    class Config:
        from_attributes = True

class ConfigurationTemplateListResponse(BaseModel):
    total: int = Field(..., description="จำนวนทั้งหมด")
    page: int = Field(..., description="หน้าปัจจุบัน")
    page_size: int = Field(..., description="ขนาดหน้า")
    templates: list[ConfigurationTemplateResponse] = Field(..., description="รายการ Template")

class ConfigurationTemplateCreateResponse(BaseModel):
    message: str
    template: ConfigurationTemplateResponse

class ConfigurationTemplateUpdateResponse(BaseModel):
    message: str
    template: ConfigurationTemplateResponse

class ConfigurationTemplateDeleteResponse(BaseModel):
    message: str

