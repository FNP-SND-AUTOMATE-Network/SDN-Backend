from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.tag_service import TagService
from app.models.tag import (
    TagCreate,
    TagUpdate,
    TagResponse,
    TagListResponse,
    TagCreateResponse,
    TagUpdateResponse,
    TagDeleteResponse,
    TagUsageResponse
)
from prisma import Prisma

router = APIRouter(prefix="/tags", tags=["Tags"])

def get_tag_service(db: Prisma = Depends(get_db)) -> TagService:
    """Get TagService instance"""
    return TagService(db)

@router.get("/", response_model=TagListResponse)
async def get_tags(
    page: int = Query(1, ge=1, description="หน้าที่ต้องการ"),
    page_size: int = Query(10, ge=1, le=500, description="จำนวนรายการต่อหน้า"),
    search: Optional[str] = Query(None, description="ค้นหาจาก tag_name, description"),
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    """
    ดึงรายการ Tag ทั้งหมด
    
    - รองรับ pagination
    - รองรับการค้นหา
    - แสดงจำนวนการใช้งานในแต่ละ model
    - ต้องเป็น authenticated user
    """
    try:
        tags, total = await tag_svc.get_tags(
            page=page,
            page_size=page_size,
            search=search,
            include_usage=include_usage
        )

        return TagListResponse(
            total=total,
            page=page,
            page_size=page_size,
            tags=tags
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงรายการ Tag: {str(e)}"
        )

@router.get("/{tag_id}", response_model=TagResponse)
async def get_tag(
    tag_id: str,
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    """
    ดึงข้อมูล Tag ตาม ID
    
    - แสดงจำนวนการใช้งาน
    - ต้องเป็น authenticated user
    """
    try:
        tag = await tag_svc.get_tag_by_id(tag_id, include_usage=include_usage)
        
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ Tag ที่ต้องการ"
            )
        
        return tag

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงข้อมูล Tag: {str(e)}"
        )

@router.get("/{tag_id}/usage", response_model=TagUsageResponse)
async def get_tag_usage(
    tag_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    """
    ดึงข้อมูลการใช้งาน Tag โดยละเอียด
    
    - แสดงรายการ Device, OS, Template ที่ใช้ Tag นี้
    - ต้องเป็น authenticated user
    """
    try:
        usage = await tag_svc.get_tag_usage(tag_id)
        
        if not usage:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ Tag ที่ต้องการ"
            )
        
        return usage

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงข้อมูลการใช้งาน Tag: {str(e)}"
        )

@router.post("/", response_model=TagCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    tag_data: TagCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    """
    สร้าง Tag ใหม่
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - tag_name ต้องไม่ซ้ำ
    """
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ENGINEER ขึ้นไป)
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์สร้าง Tag ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        tag = await tag_svc.create_tag(tag_data)
        
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถสร้าง Tag ได้"
            )

        return TagCreateResponse(
            message="สร้าง Tag สำเร็จ",
            tag=tag
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
            detail=f"เกิดข้อผิดพลาดในการสร้าง Tag: {str(e)}"
        )

@router.put("/{tag_id}", response_model=TagUpdateResponse)
async def update_tag(
    tag_id: str,
    update_data: TagUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    """
    อัปเดต Tag
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - สามารถอัปเดตบางฟิลด์ได้
    """
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ENGINEER ขึ้นไป)
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์แก้ไข Tag ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        tag = await tag_svc.update_tag(tag_id, update_data)
        
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถอัปเดต Tag ได้"
            )

        return TagUpdateResponse(
            message="อัปเดต Tag สำเร็จ",
            tag=tag
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
            detail=f"เกิดข้อผิดพลาดในการอัปเดต Tag: {str(e)}"
        )

@router.delete("/{tag_id}", response_model=TagDeleteResponse)
async def delete_tag(
    tag_id: str,
    force: bool = Query(False, description="บังคับลบแม้มีการใช้งาน (ใช้ด้วยความระมัดระวัง)"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    """
    ลบ Tag
    
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
                    detail="ไม่มีสิทธิ์ลบ Tag ต้องเป็น ADMIN หรือ OWNER"
                )

        success = await tag_svc.delete_tag(tag_id, force=force)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบ Tag ได้"
            )

        return TagDeleteResponse(
            message="ลบ Tag สำเร็จ"
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
            detail=f"เกิดข้อผิดพลาดในการลบ Tag: {str(e)}"
        )

