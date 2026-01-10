from pydantic import BaseModel, EmailStr, validator, Field
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
    access_token: Optional[str] = None
    token_type: str = "bearer"
    user_id: str
    email: str
    name: Optional[str]
    surname: Optional[str]
    role: str
    requires_totp: bool = False
    temp_token: Optional[str] = None


class VerifyTotpLoginRequest(BaseModel):
    temp_token: str
    otp_code: str

    @validator('otp_code')
    def validate_otp_code(cls, v):
        if not v.isdigit() or len(v) != 6:
            raise ValueError('OTP ต้องเป็นตัวเลข 6 หลัก')
        return v


# Error Response
class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# TOTP Setup Response
class TotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


# TOTP Verify Request
class TotpVerifyRequest(BaseModel):
    secret: str  # Secret ที่ได้จาก /auth/mfa/setup
    otp_code: str

    @validator('otp_code')
    def validate_otp_code(cls, v):
        if not v.isdigit() or len(v) != 6:
            raise ValueError('OTP ต้องเป็นตัวเลข 6 หลัก')
        return v
    
    @validator('secret')
    def validate_secret(cls, v):
        if not v or len(v.strip()) < 16:
            raise ValueError('Secret ต้องมีความยาวอย่างน้อย 16 ตัวอักษร')
        return v.strip()


class TotpVerifyOtpRequest(BaseModel):
    otp_code: str

    @validator('otp_code')
    def validate_otp_code(cls, v):
        if not v.isdigit() or len(v) != 6:
            raise ValueError('OTP ต้องเป็นตัวเลข 6 หลัก')
        return v

# TOTP Disable Request
class TotpDisableRequest(BaseModel):
    password: str


# Forgot Password Request
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


# Forgot Password Response
class ForgotPasswordResponse(BaseModel):
    message: str
    email: str
    expires_at: datetime


# Reset Password Request
class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str = Field(..., min_length=8, description="รหัสผ่านใหม่ขั้นต่ำ 8 ตัวอักษร")
    
    @validator('otp_code')
    def validate_otp_code(cls, v):
        if not v.isdigit() or len(v) != 6:
            raise ValueError('OTP ต้องเป็นตัวเลข 6 หลัก')
        return v


# Reset Password Response
class ResetPasswordResponse(BaseModel):
    message: str

