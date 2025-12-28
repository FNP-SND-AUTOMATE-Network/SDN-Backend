from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class PolicyBase(BaseModel):
    policy_name: str = Field(..., description="ชื่อ Policy (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Policy", max_length=1000)
    parent_policy_id: Optional[str] = Field(None, description="Parent Policy ID (สำหรับ hierarchy)")

class PolicyCreate(PolicyBase):
    pass

class PolicyUpdate(BaseModel):
    policy_name: Optional[str] = Field(None, description="ชื่อ Policy (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Policy", max_length=1000)
    parent_policy_id: Optional[str] = Field(None, description="Parent Policy ID (สำหรับ hierarchy)")

class RelatedUserInfo(BaseModel):
    id: str
    email: str
    name: Optional[str]
    surname: Optional[str]

class ParentPolicyInfo(BaseModel):
    id: str
    policy_name: str

class PolicyResponse(PolicyBase):
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
    total: int = Field(..., description="จำนวนทั้งหมด")
    page: int = Field(..., description="หน้าปัจจุบัน")
    page_size: int = Field(..., description="ขนาดหน้า")
    policies: list[PolicyResponse] = Field(..., description="รายการ Policy")

class PolicyCreateResponse(BaseModel):
    message: str
    policy: PolicyResponse

class PolicyUpdateResponse(BaseModel):
    message: str
    policy: PolicyResponse

class PolicyDeleteResponse(BaseModel):
    message: str

class PolicyHierarchyResponse(BaseModel):
    id: str
    policy_name: str
    description: Optional[str]
    parent_policy_id: Optional[str]
    children: List['PolicyHierarchyResponse'] = Field(default_factory=list)
    device_count: int
    backup_count: int

# Enable forward references
PolicyHierarchyResponse.model_rebuild()

