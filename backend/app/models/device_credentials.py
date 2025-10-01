from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DeviceCredentialsBase(BaseModel):
    """Base model สำหรับ Device Network Credentials"""
    device_username: str = Field(..., description="ชื่อผู้ใช้สำหรับเข้าใช้งานอุปกรณ์เครือข่าย", min_length=1, max_length=100)


class DeviceCredentialsCreate(DeviceCredentialsBase):
    """Model สำหรับสร้าง Device Credentials ใหม่"""
    device_password: str = Field(..., description="รหัสผ่านสำหรับเข้าใช้งานอุปกรณ์เครือข่าย", min_length=1, max_length=200)


class DeviceCredentialsUpdate(BaseModel):
    """Model สำหรับอัปเดต Device Credentials"""
    device_username: Optional[str] = Field(None, description="ชื่อผู้ใช้สำหรับเข้าใช้งานอุปกรณ์เครือข่าย", min_length=1, max_length=100)
    device_password: Optional[str] = Field(None, description="รหัสผ่านใหม่สำหรับเข้าใช้งานอุปกรณ์เครือข่าย", min_length=1, max_length=200)


class DeviceCredentialsResponse(DeviceCredentialsBase):
    """Model สำหรับการตอบกลับ Device Credentials (ไม่แสดงรหัสผ่าน)"""
    id: str = Field(..., description="ID ของ Device Credentials")
    user_id: str = Field(..., description="ID ของผู้ใช้")
    has_password: bool = Field(..., description="มีรหัสผ่านหรือไม่")
    created_at: datetime = Field(..., description="วันที่สร้าง")
    updated_at: datetime = Field(..., description="วันที่อัปเดตล่าสุด")
    
    class Config:
        from_attributes = True


class DeviceCredentialsCreateResponse(BaseModel):
    """Model สำหรับการตอบกลับหลังจากสร้าง Device Credentials"""
    message: str = Field(..., description="ข้อความแจ้งผลลัพธ์")
    device_credentials: DeviceCredentialsResponse = Field(..., description="ข้อมูล Device Credentials ที่สร้างแล้ว")


class DeviceCredentialsUpdateResponse(BaseModel):
    """Model สำหรับการตอบกลับหลังจากอัปเดต Device Credentials"""
    message: str = Field(..., description="ข้อความแจ้งผลลัพธ์")
    device_credentials: DeviceCredentialsResponse = Field(..., description="ข้อมูล Device Credentials ที่อัปเดตแล้ว")


class DeviceCredentialsDeleteResponse(BaseModel):
    """Model สำหรับการตอบกลับหลังจากลบ Device Credentials"""
    message: str = Field(..., description="ข้อความแจ้งผลลัพธ์")
