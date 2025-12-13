from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class PolicyBase(BaseModel):
    """Base model สำหรับ Policy"""
    policy_name: str = Field(..., description="ชื่อ Policy (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Policy", max_length=1000)
    parent_policy_id: Optional[str] = Field(None, description="Parent Policy ID (สำหรับ hierarchy)")

class PolicyCreate(PolicyBase):
    """Model สำหรับสร้าง Policy ใหม่"""
    pass

class PolicyUpdate(BaseModel):
    """Model สำหรับอัปเดต Policy"""
    policy_name: Optional[str] = Field(None, description="ชื่อ Policy (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Policy", max_length=1000)
    parent_policy_id: Optional[str] = Field(None, description="Parent Policy ID (สำหรับ hierarchy)")

class RelatedUserInfo(BaseModel):
    """ข้อมูล User แบบย่อ"""
    id: str
    email: str
    name: Optional[str]
    surname: Optional[str]

class ParentPolicyInfo(BaseModel):
    """ข้อมูล Parent Policy แบบย่อ"""
    id: str
    policy_name: str

class PolicyResponse(PolicyBase):
    """Model สำหรับ response ของ Policy"""
    id: str = Field(..., description="ID ของ Policy")
    created_by: Optional[str] = Field(None, description="สร้างโดย User ID")
    created_at: datetime
    updated_at: datetime
    
    # Related Info
    created_by_user: Optional[RelatedUserInfo] = None
    parent_policy: Optional[ParentPolicyInfo] = None
    
    # นับจำนวนการใช้งาน
    device_count: Optional[int] = Field(0, description="จำนวน Device ที่ใช้ Policy นี้")
    backup_count: Optional[int] = Field(0, description="จำนวน Backup ที่ใช้ Policy นี้")
    child_count: Optional[int] = Field(0, description="จำนวน Child Policy")
    total_usage: Optional[int] = Field(0, description="จำนวนการใช้งานทั้งหมด")

    class Config:
        from_attributes = True

class PolicyListResponse(BaseModel):
    """Model สำหรับ response ของรายการ Policy"""
    total: int = Field(..., description="จำนวนทั้งหมด")
    page: int = Field(..., description="หน้าปัจจุบัน")
    page_size: int = Field(..., description="ขนาดหน้า")
    policies: list[PolicyResponse] = Field(..., description="รายการ Policy")

class PolicyCreateResponse(BaseModel):
    """Model สำหรับ response เมื่อสร้าง Policy สำเร็จ"""
    message: str
    policy: PolicyResponse

class PolicyUpdateResponse(BaseModel):
    """Model สำหรับ response เมื่ออัปเดต Policy สำเร็จ"""
    message: str
    policy: PolicyResponse

class PolicyDeleteResponse(BaseModel):
    """Model สำหรับ response เมื่อลบ Policy สำเร็จ"""
    message: str

class PolicyHierarchyResponse(BaseModel):
    """Model สำหรับแสดง Policy hierarchy"""
    id: str
    policy_name: str
    description: Optional[str]
    parent_policy_id: Optional[str]
    children: List['PolicyHierarchyResponse'] = Field(default_factory=list)
    device_count: int
    backup_count: int

# Enable forward references
PolicyHierarchyResponse.model_rebuild()

