from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class BackupStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"
    OTHER = "OTHER"

class ScheduleType(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    CUSTOM_CRON = "CUSTOM_CRON"
    NONE = "NONE"

class BackupBase(BaseModel):
    backup_name: str = Field(..., description="Backup Profile Name (Must be unique)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="Backup Profile Description", max_length=1000)
    status: BackupStatus = Field(default=BackupStatus.ONLINE, description="Profile Status")
    auto_backup: bool = Field(default=False, description="Enable Auto Backup")
    schedule_type: ScheduleType = Field(default=ScheduleType.NONE, description="Schedule Type")
    cron_expression: Optional[str] = Field(None, description="Cron expression for scheduling")
    retention_days: int = Field(default=30, description="Keep backups for this many days")

class BackupCreate(BackupBase):
    pass

class BackupUpdate(BaseModel):
    backup_name: Optional[str] = Field(None, description="Backup Profile Name (Must be unique)", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="Backup Profile Description", max_length=1000)
    status: Optional[BackupStatus] = Field(None, description="Profile Status")
    auto_backup: Optional[bool] = Field(None, description="Enable Auto Backup")
    schedule_type: Optional[ScheduleType] = Field(None, description="Schedule Type")
    cron_expression: Optional[str] = Field(None, description="Cron expression for scheduling")
    retention_days: Optional[int] = Field(None, description="Keep backups for this many days")

class RelatedDeviceBackup(BaseModel):
    id: str
    device_name: str

class BackupResponse(BackupBase):
    id: str = Field(..., description="Backup ID")
    created_at: datetime
    updated_at: datetime
    
    # Related Target Devices
    devices: list[RelatedDeviceBackup] = Field(default_factory=list, description="Devices using this backup profile")
    
    device_count: Optional[int] = Field(0, description="Number of devices using this backup")

    class Config:
        from_attributes = True

class BackupListResponse(BaseModel):
    total: int = Field(..., description="Total profiles")
    page: int = Field(..., description="Current page")
    page_size: int = Field(..., description="Page size")
    backups: list[BackupResponse] = Field(..., description="List of backups")

class BackupCreateResponse(BaseModel):
    message: str
    backup: BackupResponse

class BackupUpdateResponse(BaseModel):
    message: str
    backup: BackupResponse

class BackupDeleteResponse(BaseModel):
    message: str

