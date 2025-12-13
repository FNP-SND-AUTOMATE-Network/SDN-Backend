from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class BackupStatus(str, Enum):
    """สถานะของ Backup"""
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"
    OTHER = "OTHER"

class BackupBase(BaseModel):
    """Base model สำหรับ Backup"""
    backup_name: str = Field(..., description="ชื่อ Backup (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Backup", max_length=1000)
    policy_id: Optional[str] = Field(None, description="Policy ID ที่เชื่อมโยง")
    os_id: Optional[str] = Field(None, description="Operating System ID ที่เชื่อมโยง")
    status: BackupStatus = Field(default=BackupStatus.ONLINE, description="สถานะของ Backup")
    auto_backup: bool = Field(default=False, description="เปิดใช้งาน Auto Backup")

class BackupCreate(BackupBase):
    """Model สำหรับสร้าง Backup ใหม่"""
    pass

class BackupUpdate(BaseModel):
    """Model สำหรับอัปเดต Backup"""
    backup_name: Optional[str] = Field(None, description="ชื่อ Backup (ต้องไม่ซ้ำ)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="คำอธิบาย Backup", max_length=1000)
    policy_id: Optional[str] = Field(None, description="Policy ID ที่เชื่อมโยง")
    os_id: Optional[str] = Field(None, description="Operating System ID ที่เชื่อมโยง")
    status: Optional[BackupStatus] = Field(None, description="สถานะของ Backup")
    auto_backup: Optional[bool] = Field(None, description="เปิดใช้งาน Auto Backup")

class RelatedPolicyInfoBackup(BaseModel):
    """ข้อมูล Policy แบบย่อ"""
    id: str
    policy_name: str

class RelatedOSInfoBackup(BaseModel):
    """ข้อมูล OS แบบย่อ"""
    id: str
    os_name: str
    os_type: str

class BackupResponse(BackupBase):
    """Model สำหรับ response ของ Backup"""
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
    """Model สำหรับ response ของรายการ Backup"""
    total: int = Field(..., description="จำนวนทั้งหมด")
    page: int = Field(..., description="หน้าปัจจุบัน")
    page_size: int = Field(..., description="ขนาดหน้า")
    backups: list[BackupResponse] = Field(..., description="รายการ Backup")

class BackupCreateResponse(BaseModel):
    """Model สำหรับ response เมื่อสร้าง Backup สำเร็จ"""
    message: str
    backup: BackupResponse

class BackupUpdateResponse(BaseModel):
    """Model สำหรับ response เมื่ออัปเดต Backup สำเร็จ"""
    message: str
    backup: BackupResponse

class BackupDeleteResponse(BaseModel):
    """Model สำหรับ response เมื่อลบ Backup สำเร็จ"""
    message: str

