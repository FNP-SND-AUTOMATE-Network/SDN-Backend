from pydantic import BaseModel, Field
from typing import Optional, List
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

class ConfigurationTemplateCreate(ConfigurationTemplateBase):
    tag_names: Optional[List[str]] = Field(None, description="รายการ Tag names ที่เชื่อมโยง")

class ConfigurationTemplateUpdate(BaseModel):
    template_name: Optional[str] = Field(None, description="ชื่อ Template (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Template", max_length=1000)
    template_type: Optional[TemplateType] = Field(None, description="ประเภทของ Template")
    tag_names: Optional[List[str]] = Field(None, description="รายการ Tag names ที่เชื่อมโยง")

class RelatedTagInfoTemplate(BaseModel):
    tag_id: str
    tag_name: str
    color: str
    type: str

class ConfigurationTemplateDetailResponse(BaseModel):
    id: str
    config_content: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    updated_at: datetime

    class Config:
        from_attributes = True

class ConfigurationTemplateResponse(ConfigurationTemplateBase):
    id: str = Field(..., description="ID ของ Template")
    created_at: datetime
    updated_at: datetime
    
    # Related Info - many-to-many relation with tags
    tags: List[RelatedTagInfoTemplate] = Field(default=[], description="Tags ที่เชื่อมโยง")
    
    # Detail
    detail: Optional[ConfigurationTemplateDetailResponse] = Field(None, description="รายละเอียด Config (ถ้ามี)")

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

