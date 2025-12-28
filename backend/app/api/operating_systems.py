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
    return OperatingSystemService(db)

def get_file_service(db: Prisma = Depends(get_db)) -> OSFileService:
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
            detail=f"Error fetching operating systems: {str(e)}"
        )

@router.get("/{os_id}", response_model=OperatingSystemResponse)
async def get_operating_system(
    os_id: str,
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    try:
        operating_system = await os_svc.get_operating_system_by_id(os_id, include_usage=include_usage)
        
        if not operating_system:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Operating System not found"
            )
        
        return operating_system

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching operating system: {str(e)}"
        )

@router.get("/{os_id}/usage", response_model=OperatingSystemUsageResponse)
async def get_operating_system_usage(
    os_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    try:
        usage = await os_svc.get_operating_system_usage(os_id)
        
        if not usage:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Operating System not found"
            )
        
        return usage

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get operating system usage: {str(e)}"
        )

@router.post("/", response_model=OperatingSystemCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_operating_system(
    os_data: OperatingSystemCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ENGINEER ขึ้นไป)
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to create an operating system"
            )

        operating_system = await os_svc.create_operating_system(os_data)
        
        if not operating_system:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create operating system"
            )

        return OperatingSystemCreateResponse(
            message="Operating system created successfully",
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
            detail=f"Failed to create operating system: {str(e)}"
        )

@router.put("/{os_id}", response_model=OperatingSystemUpdateResponse)
async def update_operating_system(
    os_id: str,
    update_data: OperatingSystemUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ENGINEER ขึ้นไป)
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update an operating system"
            )

        operating_system = await os_svc.update_operating_system(os_id, update_data)
        
        if not operating_system:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update operating system"
            )

        return OperatingSystemUpdateResponse(
            message="Operating system updated successfully",
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
            detail=f"Error updating operating system: {str(e)}"
        )

@router.delete("/{os_id}", response_model=OperatingSystemDeleteResponse)
async def delete_operating_system(
    os_id: str,
    force: bool = Query(False, description="Force delete even if in use"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    try:
        # ตรวจสอบสิทธิ์
        if force:
            # บังคับลบต้องเป็น OWNER เท่านั้น
            if current_user["role"] != "OWNER":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to force delete an operating system"
                )
        else:
            # ลบปกติต้องเป็น ADMIN หรือ OWNER
            if current_user["role"] not in ["ADMIN", "OWNER"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to delete an operating system"
                )

        success = await os_svc.delete_operating_system(os_id, force=force)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete operating system"
            )

        return OperatingSystemDeleteResponse(
            message="Operating system deleted successfully"
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
            detail=f"Failed to delete operating system: {str(e)}"
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
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to upload an OS file"
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
                detail="Failed to upload OS file"
            )

        return OSFileUploadResponse(
            message=f"OS file {file.filename} uploaded successfully",
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
            detail=f"Failed to upload OS file: {str(e)}"
        )

@router.get("/{os_id}/files", response_model=OSFileListResponse)
async def get_os_files(
    os_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    file_svc: OSFileService = Depends(get_file_service)
):
    try:
        files = await file_svc.get_files_by_os(os_id)

        return OSFileListResponse(
            total=len(files),
            files=files
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get OS files: {str(e)}"
        )

@router.get("/{os_id}/files/{file_id}/download")
async def download_os_file(
    os_id: str,
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    file_svc: OSFileService = Depends(get_file_service)
):
    try:
        # ดึงข้อมูลไฟล์
        os_file = await file_svc.get_file_by_id(file_id)
        
        if not os_file or os_file.os_id != os_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )

        # ดึง path ของไฟล์
        file_path = file_svc.get_file_path(file_id, os_file.file_path)
        
        if not file_path or not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
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
            detail=f"Failed to download OS file: {str(e)}"
        )

@router.delete("/{os_id}/files/{file_id}", response_model=OSFileDeleteResponse)
async def delete_os_file(
    os_id: str,
    file_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    file_svc: OSFileService = Depends(get_file_service)
):
    try:
        if current_user["role"] not in ["ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete an OS file"
            )

        # ตรวจสอบว่าไฟล์เป็นของ OS นี้
        os_file = await file_svc.get_file_by_id(file_id)
        if not os_file or os_file.os_id != os_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )

        success = await file_svc.delete_file(file_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete OS file"
            )

        return OSFileDeleteResponse(
            message="OS file deleted successfully"
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
            detail=f"Failed to delete OS file: {str(e)}"
        )

# ========= OS Tag Management Endpoints =========

@router.post("/{os_id}/tags", response_model=OperatingSystemUpdateResponse)
async def assign_tags_to_os(
    os_id: str,
    tag_ids: list[str],
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to manage tags"
            )

        os = await os_svc.assign_tags(os_id, tag_ids)
        
        if not os:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to assign tags"
            )

        return OperatingSystemUpdateResponse(
            message=f"Successfully assigned {len(tag_ids)} tags",
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
            detail=f"Failed to assign tags: {str(e)}"
        )

@router.delete("/{os_id}/tags", response_model=OperatingSystemUpdateResponse)
async def remove_tags_from_os(
    os_id: str,
    tag_ids: list[str],
    current_user: Dict[str, Any] = Depends(get_current_user),
    os_svc: OperatingSystemService = Depends(get_os_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to manage tags"
            )

        os = await os_svc.remove_tags(os_id, tag_ids)
        
        if not os:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to remove tags"
            )

        return OperatingSystemUpdateResponse(
            message=f"Successfully removed {len(tag_ids)} tags",
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
            detail=f"Failed to remove tags: {str(e)}"
        )

