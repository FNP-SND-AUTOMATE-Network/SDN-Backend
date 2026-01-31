from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

class UserRole(str, Enum):
    VIEWER = "VIEWER"
    ENGINEER = "ENGINEER"
    ADMIN = "ADMIN"
    OWNER = "OWNER"

# ========= User Request Models =========

class UserCreateRequest(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    surname: Optional[str] = None
    password: str = Field(..., min_length=8, description="รหัสผ่านขั้นต่ำ 8 ตัวอักษร")
    role: UserRole = UserRole.VIEWER

class UserUpdateRequest(BaseModel):
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    surname: Optional[str] = None
    role: Optional[UserRole] = None
    email_verified: Optional[bool] = None
    has_strong_mfa: Optional[bool] = None

class UserChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, description="รหัสผ่านใหม่ขั้นต่ำ 8 ตัวอักษร")

# ========= User Response Models =========

class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    surname: Optional[str] = None
    role: UserRole
    email_verified: bool
    has_strong_mfa: bool
    created_at: datetime
    updated_at: datetime

class UserDetailResponse(UserResponse):
    totp_enabled: bool = False
    passkeys_count: int = 0
    recovery_codes_count: int = 0

class UserListResponse(BaseModel):
    users: List[UserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

# ========= User Filter Models =========

class UserFilter(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    surname: Optional[str] = None
    role: Optional[UserRole] = None
    email_verified: Optional[bool] = None
    has_strong_mfa: Optional[bool] = None
    search: Optional[str] = Field(None, description="ค้นหาใน email, name, surname")

# ========= Success Response Models =========

class UserCreateResponse(BaseModel):
    message: str
    user: UserResponse
    target_role: Optional[str] = None
    otp_expires_at: Optional[datetime] = None
    requires_otp_verification: Optional[bool] = False

class UserUpdateResponse(BaseModel):
    message: str
    user: UserResponse

class UserDeleteResponse(BaseModel):
    message: str
    user_id: str

class PasswordChangeResponse(BaseModel):
    message: str
    user_id: str

class ErrorResponse(BaseModel):
    detail: str
