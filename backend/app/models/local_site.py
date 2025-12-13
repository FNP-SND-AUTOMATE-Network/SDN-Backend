from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class SiteType(str, Enum):
    """ประเภทของสถานที่"""
    DATA_CENTER = "DataCenter"
    BRANCH = "BRANCH"
    OTHER = "OTHER"

class LocalSiteBase(BaseModel):
    """Base model สำหรับ LocalSite"""
    site_code: str = Field(..., description="รหัสสถานที่ (ต้องไม่ซ้ำ)", min_length=1, max_length=50)
    site_name: Optional[str] = Field(None, description="ชื่อสถานที่", max_length=200)
    site_type: SiteType = Field(SiteType.DATA_CENTER, description="ประเภทสถานที่")
    building_name: Optional[str] = Field(None, description="ชื่ออาคาร", max_length=200)
    floor_number: Optional[int] = Field(None, description="หมายเลขชั้น", ge=0)
    rack_number: Optional[int] = Field(None, description="หมายเลขแร็ค", ge=0)
    address: Optional[str] = Field(None, description="ที่อยู่", max_length=500)
    address_detail: Optional[str] = Field(None, description="รายละเอียดที่อยู่เพิ่มเติม", max_length=500)
    sub_district: Optional[str] = Field(None, description="ตำบล/แขวง", max_length=100)
    district: Optional[str] = Field(None, description="อำเภอ/เขต", max_length=100)
    city: Optional[str] = Field(None, description="จังหวัด/เมือง", max_length=100)
    zip_code: Optional[str] = Field(None, description="รหัสไปรษณีย์", max_length=10)
    country: Optional[str] = Field(None, description="ประเทศ", max_length=100)

class LocalSiteCreate(LocalSiteBase):
    """Model สำหรับสร้าง LocalSite ใหม่"""
    pass

class LocalSiteUpdate(BaseModel):
    """Model สำหรับอัปเดต LocalSite"""
    site_code: Optional[str] = Field(None, description="รหัสสถานที่ (ต้องไม่ซ้ำ)", min_length=1, max_length=50)
    site_name: Optional[str] = Field(None, description="ชื่อสถานที่", max_length=200)
    site_type: Optional[SiteType] = Field(None, description="ประเภทสถานที่")
    building_name: Optional[str] = Field(None, description="ชื่ออาคาร", max_length=200)
    floor_number: Optional[int] = Field(None, description="หมายเลขชั้น", ge=0)
    rack_number: Optional[int] = Field(None, description="หมายเลขแร็ค", ge=0)
    address: Optional[str] = Field(None, description="ที่อยู่", max_length=500)
    address_detail: Optional[str] = Field(None, description="รายละเอียดที่อยู่เพิ่มเติม", max_length=500)
    sub_district: Optional[str] = Field(None, description="ตำบล/แขวง", max_length=100)
    district: Optional[str] = Field(None, description="อำเภอ/เขต", max_length=100)
    city: Optional[str] = Field(None, description="จังหวัด/เมือง", max_length=100)
    zip_code: Optional[str] = Field(None, description="รหัสไปรษณีย์", max_length=10)
    country: Optional[str] = Field(None, description="ประเทศ", max_length=100)

class LocalSiteResponse(LocalSiteBase):
    """Model สำหรับ response ของ LocalSite"""
    id: str = Field(..., description="ID ของสถานที่")
    created_at: datetime
    updated_at: datetime
    device_count: Optional[int] = Field(0, description="จำนวนอุปกรณ์ที่เชื่อมโยง")

    class Config:
        from_attributes = True

class LocalSiteListResponse(BaseModel):
    """Model สำหรับ response ของรายการ LocalSite"""
    total: int = Field(..., description="จำนวนทั้งหมด")
    page: int = Field(..., description="หน้าปัจจุบัน")
    page_size: int = Field(..., description="ขนาดหน้า")
    sites: list[LocalSiteResponse] = Field(..., description="รายการสถานที่")

class LocalSiteCreateResponse(BaseModel):
    """Model สำหรับ response เมื่อสร้าง LocalSite สำเร็จ"""
    message: str
    site: LocalSiteResponse

class LocalSiteUpdateResponse(BaseModel):
    """Model สำหรับ response เมื่ออัปเดต LocalSite สำเร็จ"""
    message: str
    site: LocalSiteResponse

class LocalSiteDeleteResponse(BaseModel):
    """Model สำหรับ response เมื่อลบ LocalSite สำเร็จ"""
    message: str

