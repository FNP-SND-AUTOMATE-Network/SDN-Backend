from pydantic import BaseModel, EmailStr, validator
from typing import Optional
from datetime import datetime


# Register Request
class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    surname: str
    password: str
    confirm_password: str

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร')
        return v

    @validator('confirm_password')
    def passwords_match(cls, v, values, **kwargs):
        if 'password' in values and v != values['password']:
            raise ValueError('รหัสผ่านไม่ตรงกัน')
        return v

    @validator('name', 'surname')
    def validate_names(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError('ชื่อและนามสกุลต้องมีอย่างน้อย 2 ตัวอักษร')
        return v.strip()


# Register Response
class RegisterResponse(BaseModel):
    message: str
    email: str
    expires_at: datetime


# Verify OTP Request
class VerifyOtpRequest(BaseModel):
    email: EmailStr
    otp_code: str

    @validator('otp_code')
    def validate_otp_code(cls, v):
        if not v.isdigit() or len(v) != 6:
            raise ValueError('OTP ต้องเป็นตัวเลข 6 หลัก')
        return v


# Verify OTP Response
class VerifyOtpResponse(BaseModel):
    message: str
    user_id: str
    email: str
    email_verified: bool


# Resend OTP Request
class ResendOtpRequest(BaseModel):
    email: EmailStr


# Resend OTP Response
class ResendOtpResponse(BaseModel):
    message: str
    email: str
    expires_at: datetime


# Login Request
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @validator('password')
    def validate_password(cls, v):
        if not v or len(v.strip()) < 1:
            raise ValueError('กรุณากรอกรหัสผ่าน')
        return v


# Login Response
class LoginResponse(BaseModel):
    message: str
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    name: Optional[str]
    surname: Optional[str]
    role: str


# Error Response
class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
