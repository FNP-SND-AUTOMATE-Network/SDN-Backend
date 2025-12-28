from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class OSFileBase(BaseModel):
    file_name: str = Field(..., description="ชื่อไฟล์ต้นฉบับ", max_length=500)
    version: Optional[str] = Field(None, description="Version ของ OS (เช่น 15.7, 17.3)", max_length=50)

class OSFileCreate(OSFileBase):
    os_id: str = Field(..., description="Operating System ID")
    file_path: str = Field(..., description="Path หรือ URL ของไฟล์")
    file_size: int = Field(..., description="ขนาดไฟล์ (bytes)", ge=0)
    file_type: Optional[str] = Field(None, description="MIME type", max_length=100)
    checksum: Optional[str] = Field(None, description="MD5 หรือ SHA256 checksum", max_length=100)

class RelatedUserInfoFile(BaseModel):
    id: str
    email: str
    name: Optional[str]
    surname: Optional[str]

class RelatedOSInfoFile(BaseModel):
    id: str
    os_name: str
    os_type: str

class OSFileResponse(BaseModel):
    id: str
    os_id: str
    file_name: str
    file_path: str
    file_size: int
    file_type: Optional[str]
    version: Optional[str]
    checksum: Optional[str]
    uploaded_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    # Related Info
    uploaded_by_user: Optional[RelatedUserInfoFile] = None
    operating_system: Optional[RelatedOSInfoFile] = None

    class Config:
        from_attributes = True

class OSFileListResponse(BaseModel):
    total: int
    files: list[OSFileResponse]

class OSFileUploadResponse(BaseModel):
    message: str
    file: OSFileResponse

class OSFileDeleteResponse(BaseModel):
    message: str

class OSFileDownloadInfo(BaseModel):
    file_name: str
    file_size: int
    file_type: Optional[str]
    download_url: str

