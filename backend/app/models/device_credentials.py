from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DeviceCredentialsBase(BaseModel):
    device_username: str = Field(..., description="ชื่อผู้ใช้สำหรับเข้าใช้งานอุปกรณ์เครือข่าย", min_length=1, max_length=100)


class DeviceCredentialsCreate(DeviceCredentialsBase):
    device_password: str = Field(..., description="รหัสผ่านสำหรับเข้าใช้งานอุปกรณ์เครือข่าย", min_length=1, max_length=72)


class DeviceCredentialsUpdate(BaseModel):
    device_username: Optional[str] = Field(None, description="ชื่อผู้ใช้สำหรับเข้าใช้งานอุปกรณ์เครือข่าย", min_length=1, max_length=100)
    device_password: Optional[str] = Field(None, description="รหัสผ่านใหม่สำหรับเข้าใช้งานอุปกรณ์เครือข่าย", min_length=1, max_length=72)


class DeviceCredentialsResponse(DeviceCredentialsBase):
    id: str = Field(..., description="ID ของ Device Credentials")
    user_id: str = Field(..., description="ID ของผู้ใช้")
    has_password: bool = Field(..., description="มีรหัสผ่านหรือไม่")
    created_at: datetime = Field(..., description="วันที่สร้าง")
    updated_at: datetime = Field(..., description="วันที่อัปเดตล่าสุด")
    
    class Config:
        from_attributes = True


class DeviceCredentialsCreateResponse(BaseModel):
    message: str = Field(..., description="ข้อความแจ้งผลลัพธ์")
    device_credentials: DeviceCredentialsResponse = Field(..., description="ข้อมูล Device Credentials ที่สร้างแล้ว")


class DeviceCredentialsUpdateResponse(BaseModel):
    message: str = Field(..., description="ข้อความแจ้งผลลัพธ์")
    device_credentials: DeviceCredentialsResponse = Field(..., description="ข้อมูล Device Credentials ที่อัปเดตแล้ว")


class DeviceCredentialsDeleteResponse(BaseModel):
    message: str = Field(..., description="ข้อความแจ้งผลลัพธ์")


class DeviceCredentialsVerifyRequest(BaseModel):
    username: str = Field(..., description="ชื่อผู้ใช้ที่ต้องการตรวจสอบ", min_length=1)
    password: str = Field(..., description="รหัสผ่านที่ต้องการตรวจสอบ", min_length=1)
