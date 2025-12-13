from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.operating_system_service import OperatingSystemService
from app.services.os_file_service import OSFileService
from app.models.operating_system import (
    OperatingSystemCreate,
    OperatingSystemUpdate,
    OperatingSystemResponse,
    OperatingSystemListResponse,
    OperatingSystemCreateResponse,
    OperatingSystemUpdateResponse,
    OperatingSystemDeleteResponse,
    OperatingSystemUsageResponse,
    OsType
)
from app.models.os_file import (
    OSFileListResponse,
    OSFileUploadResponse,
    OSFileDeleteResponse,
    OSFileResponse
)
from prisma import Prisma

router = APIRouter(prefix="/operating-systems", tags=["Operating Systems"])

def get_os_service(db: Prisma = Depends(get_db)) -> OperatingSystemService:
    """Get OperatingSystemService instance"""
    return OperatingSystemService(db)

def get_file_service(db: Prisma = Depends(get_db)) -> OSFileService:
    """Get OSFileService instance"""
    return OSFileService(db)

@router.get("/", response_model=OperatingSystemListResponse)
async def get_operating_systems(
    page: int = Query(1, ge=1, description="หน้าที่ต้องการ"),
    page_size: int = Query(20, ge=1, le=100, description="จำนวนรายการต่อหน้า"),
    os_type: Optional[str] = Query(None, description="กรองตามประเภท OS"),
    search: Optional[str] = Query(None, description="ค้นหาจาก os_name, description"),
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    """
    ดึงรายการ Operating System ทั้งหมด
    
    - รองรับ pagination
    - รองรับ filter ตาม os_type และ tag_id
    - รองรับการค้นหา
    - แสดงจำนวนการใช้งานใน Device และ Backup
    - ต้องเป็น authenticated user
    """
    try:
        operating_systems, total = await os_svc.get_operating_systems(
            page=page,
            page_size=page_size,
            os_type=os_type,
            search=search,
            include_usage=include_usage
        )

        return OperatingSystemListResponse(
            total=total,
            page=page,
            page_size=page_size,
            operating_systems=operating_systems
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงรายการ Operating System: {str(e)}"
        )

@router.get("/{os_id}", response_model=OperatingSystemResponse)
async def get_operating_system(
    os_id: str,
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    """
    ดึงข้อมูล Operating System ตาม ID
    
    - แสดงจำนวนการใช้งาน
    - แสดงข้อมูล Tag ที่เชื่อมโยง
    - ต้องเป็น authenticated user
    """
    try:
        operating_system = await os_svc.get_operating_system_by_id(os_id, include_usage=include_usage)
        
        if not operating_system:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ Operating System ที่ต้องการ"
            )
        
        return operating_system

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงข้อมูล Operating System: {str(e)}"
        )

@router.get("/{os_id}/usage", response_model=OperatingSystemUsageResponse)
async def get_operating_system_usage(
    os_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    """
    ดึงข้อมูลการใช้งาน Operating System โดยละเอียด
    
    - แสดงรายการ Device และ Backup ที่ใช้ OS นี้
    - ต้องเป็น authenticated user
    """
    try:
        usage = await os_svc.get_operating_system_usage(os_id)
        
        if not usage:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ Operating System ที่ต้องการ"
            )
        
        return usage

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงข้อมูลการใช้งาน Operating System: {str(e)}"
        )

@router.post("/", response_model=OperatingSystemCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_operating_system(
    os_data: OperatingSystemCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    """
    สร้าง Operating System ใหม่
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - os_name ต้องไม่ซ้ำ
    - สามารถเชื่อมโยงกับ Tag ได้
    """
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ENGINEER ขึ้นไป)
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์สร้าง Operating System ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        operating_system = await os_svc.create_operating_system(os_data)
        
        if not operating_system:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถสร้าง Operating System ได้"
            )

        return OperatingSystemCreateResponse(
            message="สร้าง Operating System สำเร็จ",
            operating_system=operating_system
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการสร้าง Operating System: {str(e)}"
        )

@router.put("/{os_id}", response_model=OperatingSystemUpdateResponse)
async def update_operating_system(
    os_id: str,
    update_data: OperatingSystemUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    """
    อัปเดต Operating System
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - สามารถอัปเดตบางฟิลด์ได้
    - สามารถเปลี่ยน Tag ได้
    """
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ENGINEER ขึ้นไป)
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์แก้ไข Operating System ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        operating_system = await os_svc.update_operating_system(os_id, update_data)
        
        if not operating_system:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถอัปเดต Operating System ได้"
            )

        return OperatingSystemUpdateResponse(
            message="อัปเดต Operating System สำเร็จ",
            operating_system=operating_system
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการอัปเดต Operating System: {str(e)}"
        )

@router.delete("/{os_id}", response_model=OperatingSystemDeleteResponse)
async def delete_operating_system(
    os_id: str,
    force: bool = Query(False, description="บังคับลบแม้มีการใช้งาน (ใช้ด้วยความระมัดระวัง)"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    """
    ลบ Operating System
    
    - ต้องเป็น ADMIN หรือ OWNER
    - ไม่สามารถลบถ้ามีการใช้งานอยู่ (ยกเว้น force=true)
    - force=true ต้องเป็น OWNER เท่านั้น
    """
    try:
        # ตรวจสอบสิทธิ์
        if force:
            # บังคับลบต้องเป็น OWNER เท่านั้น
            if current_user["role"] != "OWNER":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="การลบแบบบังคับต้องเป็น OWNER เท่านั้น"
                )
        else:
            # ลบปกติต้องเป็น ADMIN หรือ OWNER
            if current_user["role"] not in ["ADMIN", "OWNER"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="ไม่มีสิทธิ์ลบ Operating System ต้องเป็น ADMIN หรือ OWNER"
                )

        success = await os_svc.delete_operating_system(os_id, force=force)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบ Operating System ได้"
            )

        return OperatingSystemDeleteResponse(
            message="ลบ Operating System สำเร็จ"
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการลบ Operating System: {str(e)}"
        )

# ========= OS File Management Endpoints =========

@router.post("/{os_id}/upload", response_model=OSFileUploadResponse)
async def upload_os_file(
    os_id: str,
    file: UploadFile = File(...),
    version: Optional[str] = Form(None),
    current_user: Dict[str, Any] = Depends(get_current_user),
    file_svc: OSFileService = Depends(get_file_service)
):
    """
    อัปโหลดไฟล์สำหรับ Operating System
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - รองรับไฟล์ขนาดใหญ่ (OS images)
    - คำนวณ checksum อัตโนมัติ
    """
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์อัปโหลดไฟล์ ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        # อ่านไฟล์
        file_content = await file.read()
        
        # บันทึกไฟล์
        os_file = await file_svc.save_file(
            os_id=os_id,
            file_content=file_content,
            file_name=file.filename,
            file_type=file.content_type,
            version=version,
            user_id=current_user["id"]
        )

        if not os_file:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถอัปโหลดไฟล์ได้"
            )

        return OSFileUploadResponse(
            message=f"อัปโหลดไฟล์ {file.filename} สำเร็จ",
            file=os_file
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการอัปโหลดไฟล์: {str(e)}"
        )

@router.get("/{os_id}/files", response_model=OSFileListResponse)
async def get_os_files(
    os_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    file_svc: OSFileService = Depends(get_file_service)
):
    """
    ดึงรายการไฟล์ทั้งหมดของ Operating System
    
    - แสดงชื่อไฟล์, ขนาด, version, checksum
    - แสดงผู้อัปโหลด
    - ต้องเป็น authenticated user
    """
    try:
        files = await file_svc.get_files_by_os(os_id)

        return OSFileListResponse(
            total=len(files),
            files=files
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงรายการไฟล์: {str(e)}"
        )

@router.get("/{os_id}/files/{file_id}/download")
async def download_os_file(
    os_id: str,
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    file_svc: OSFileService = Depends(get_file_service)
):
    """
    ดาวน์โหลดไฟล์ Operating System
    
    - ส่งไฟล์กลับไปให้ client
    - ต้องเป็น authenticated user
    """
    try:
        # ดึงข้อมูลไฟล์
        os_file = await file_svc.get_file_by_id(file_id)
        
        if not os_file or os_file.os_id != os_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบไฟล์ที่ต้องการ"
            )

        # ดึง path ของไฟล์
        file_path = file_svc.get_file_path(file_id, os_file.file_path)
        
        if not file_path or not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบไฟล์ในระบบ"
            )

        # ส่งไฟล์กลับไป
        return FileResponse(
            path=str(file_path),
            filename=os_file.file_name,
            media_type=os_file.file_type or "application/octet-stream"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดาวน์โหลดไฟล์: {str(e)}"
        )

@router.delete("/{os_id}/files/{file_id}", response_model=OSFileDeleteResponse)
async def delete_os_file(
    os_id: str,
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    file_svc: OSFileService = Depends(get_file_service)
):
    """
    ลบไฟล์ Operating System
    
    - ลบทั้งไฟล์และ record
    - ต้องเป็น ADMIN หรือ OWNER
    """
    try:
        if current_user["role"] not in ["ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์ลบไฟล์ ต้องเป็น ADMIN หรือ OWNER"
            )

        # ตรวจสอบว่าไฟล์เป็นของ OS นี้
        os_file = await file_svc.get_file_by_id(file_id)
        if not os_file or os_file.os_id != os_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบไฟล์ที่ต้องการ"
            )

        success = await file_svc.delete_file(file_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบไฟล์ได้"
            )

        return OSFileDeleteResponse(
            message="ลบไฟล์สำเร็จ"
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการลบไฟล์: {str(e)}"
        )

# ========= OS Tag Management Endpoints =========

@router.post("/{os_id}/tags", response_model=OperatingSystemUpdateResponse)
async def assign_tags_to_os(
    os_id: str,
    tag_ids: list[str],
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    """
    เพิ่ม Tags ให้กับ Operating System
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - สามารถเพิ่มหลาย tags พร้อมกันได้
    """
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์จัดการ Tags ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        os = await os_svc.assign_tags(os_id, tag_ids)
        
        if not os:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถเพิ่ม Tags ได้"
            )

        return OperatingSystemUpdateResponse(
            message=f"เพิ่ม {len(tag_ids)} Tags สำเร็จ",
            operating_system=os
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการเพิ่ม Tags: {str(e)}"
        )

@router.delete("/{os_id}/tags", response_model=OperatingSystemUpdateResponse)
async def remove_tags_from_os(
    os_id: str,
    tag_ids: list[str],
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    """
    ลบ Tags ออกจาก Operating System
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - สามารถลบหลาย tags พร้อมกันได้
    """
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์จัดการ Tags ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        os = await os_svc.remove_tags(os_id, tag_ids)
        
        if not os:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบ Tags ได้"
            )

        return OperatingSystemUpdateResponse(
            message=f"ลบ {len(tag_ids)} Tags สำเร็จ",
            operating_system=os
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการลบ Tags: {str(e)}"
        )

