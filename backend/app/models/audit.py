from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class AuditAction(str, Enum):
    USER_REGISTER = "USER_REGISTER"
    USER_LOGIN = "USER_LOGIN"
    USER_LOGOUT = "USER_LOGOUT"
    USER_CREATE = "USER_CREATE"
    USER_UPDATE = "USER_UPDATE"
    USER_DELETE = "USER_DELETE"
    ENABLE_TOTP = "ENABLE_TOTP"
    DISABLE_TOTP = "DISABLE_TOTP"
    REGISTER_PASSKEY = "REGISTER_PASSKEY"
    REMOVE_PASSKEY = "REMOVE_PASSKEY"
    PROMOTE_ROLE = "PROMOTE_ROLE"
    DEMOTE_ROLE = "DEMOTE_ROLE"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    PASSWORD_RESET = "PASSWORD_RESET"

    # Device Management
    DEVICE_CREATE = "DEVICE_CREATE"
    DEVICE_UPDATE = "DEVICE_UPDATE"
    DEVICE_DELETE = "DEVICE_DELETE"
    DEVICE_MOUNT = "DEVICE_MOUNT"
    DEVICE_UNMOUNT = "DEVICE_UNMOUNT"

    # Backup Management
    BACKUP_PROFILE_CREATE = "BACKUP_PROFILE_CREATE"
    BACKUP_PROFILE_UPDATE = "BACKUP_PROFILE_UPDATE"
    BACKUP_PROFILE_DELETE = "BACKUP_PROFILE_DELETE"
    BACKUP_PROFILE_PAUSE = "BACKUP_PROFILE_PAUSE"
    BACKUP_PROFILE_RESUME = "BACKUP_PROFILE_RESUME"
    BACKUP_TRIGGER_MANUAL = "BACKUP_TRIGGER_MANUAL"

    # Configuration & Deployment
    TEMPLATE_CREATE = "TEMPLATE_CREATE"
    TEMPLATE_UPDATE = "TEMPLATE_UPDATE"
    TEMPLATE_DELETE = "TEMPLATE_DELETE"
    DEPLOYMENT_START = "DEPLOYMENT_START"

    # OS Management
    OS_FILE_UPLOAD = "OS_FILE_UPLOAD"
    OS_FILE_DELETE = "OS_FILE_DELETE"

    # Master Data & Interfaces
    INTERFACE_UPDATE = "INTERFACE_UPDATE"
    SITE_CREATE = "SITE_CREATE"
    SITE_UPDATE = "SITE_UPDATE"
    SITE_DELETE = "SITE_DELETE"
    POLICY_CREATE = "POLICY_CREATE"
    POLICY_UPDATE = "POLICY_UPDATE"
    POLICY_DELETE = "POLICY_DELETE"
    TAG_CREATE = "TAG_CREATE"
    TAG_UPDATE = "TAG_UPDATE"
    TAG_DELETE = "TAG_DELETE"


class AuditLogBase(BaseModel):
    actor_user_id: Optional[str] = Field(None, description="ID ของผู้ที่ทำการกระทำ")
    target_user_id: Optional[str] = Field(None, description="ID ของผู้ที่ถูกกระทำ")
    action: AuditAction = Field(..., description="ประเภทการกระทำ")
    details: Optional[Dict[str, Any]] = Field(None, description="รายละเอียดเพิ่มเติม")


class AuditLogCreate(AuditLogBase):
    pass


class AuditLogResponse(AuditLogBase):
    id: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class AuditLogFilter(BaseModel):
    actor_user_id: Optional[str] = None
    target_user_id: Optional[str] = None
    action: Optional[AuditAction] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class AuditLogListResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int
    limit: int
    offset: int
    has_more: bool
