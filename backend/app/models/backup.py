from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class BackupStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"
    OTHER = "OTHER"

class BackupBase(BaseModel):
    backup_name: str = Field(..., description="ชื่อ Backup (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Backup", max_length=1000)
    policy_id: Optional[str] = Field(None, description="Policy ID ที่เชื่อมโยง")
    os_id: Optional[str] = Field(None, description="Operating System ID ที่เชื่อมโยง")
    status: BackupStatus = Field(default=BackupStatus.ONLINE, description="สถานะของ Backup")
    auto_backup: bool = Field(default=False, description="เปิดใช้งาน Auto Backup")

class BackupCreate(BackupBase):
    pass

class BackupUpdate(BaseModel):
    backup_name: Optional[str] = Field(None, description="ชื่อ Backup (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Backup", max_length=1000)
    policy_id: Optional[str] = Field(None, description="Policy ID ที่เชื่อมโยง")
    os_id: Optional[str] = Field(None, description="Operating System ID ที่เชื่อมโยง")
    status: Optional[BackupStatus] = Field(None, description="สถานะของ Backup")
    auto_backup: Optional[bool] = Field(None, description="เปิดใช้งาน Auto Backup")

class RelatedPolicyInfoBackup(BaseModel):
    id: str
    policy_name: str

class RelatedOSInfoBackup(BaseModel):
    id: str
    os_name: str
    os_type: str

class BackupResponse(BackupBase):
    id: str = Field(..., description="ID ของ Backup")
    created_at: datetime
    updated_at: datetime
    
    # Related Info
    policy: Optional[RelatedPolicyInfoBackup] = None
    operating_system: Optional[RelatedOSInfoBackup] = None
    
    # นับจำนวนการใช้งาน
    device_count: Optional[int] = Field(0, description="จำนวน Device ที่ใช้ Backup นี้")

    class Config:
        from_attributes = True

class BackupListResponse(BaseModel):
    total: int = Field(..., description="จำนวนทั้งหมด")
    page: int = Field(..., description="หน้าปัจจุบัน")
    page_size: int = Field(..., description="ขนาดหน้า")
    backups: list[BackupResponse] = Field(..., description="รายการ Backup")

class BackupCreateResponse(BaseModel):
    message: str
    backup: BackupResponse

class BackupUpdateResponse(BaseModel):
    message: str
    backup: BackupResponse

class BackupDeleteResponse(BaseModel):
    message: str

