from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.backup_service import BackupService
from app.models.backup import (
    BackupCreate,
    BackupUpdate,
    BackupResponse,
    BackupListResponse,
    BackupCreateResponse,
    BackupUpdateResponse,
    BackupDeleteResponse,
    BackupStatus
)
from prisma import Prisma

router = APIRouter(prefix="/backups", tags=["Backups"])

def get_backup_service(db: Prisma = Depends(get_db)) -> BackupService:
    """Get BackupService instance"""
    return BackupService(db)

@router.get("/", response_model=BackupListResponse)
async def get_backups(
    page: int = Query(1, ge=1, description="หน้าที่ต้องการ"),
    page_size: int = Query(20, ge=1, le=100, description="จำนวนรายการต่อหน้า"),
    status: Optional[str] = Query(None, description="กรองตามสถานะ"),
    search: Optional[str] = Query(None, description="ค้นหาจาก backup_name, description"),
    policy_id: Optional[str] = Query(None, description="กรองตาม Policy ID"),
    os_id: Optional[str] = Query(None, description="กรองตาม OS ID"),
    auto_backup: Optional[bool] = Query(None, description="กรองตาม auto_backup"),
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service)
):
    """
    ดึงรายการ Backup ทั้งหมด
    
    - รองรับ pagination และ filter หลายแบบ
    - แสดงข้อมูล Policy และ OS ที่เชื่อมโยง
    - ต้องเป็น authenticated user
    """
    try:
        backups, total = await backup_svc.get_backups(
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            policy_id=policy_id,
            os_id=os_id,
            auto_backup=auto_backup,
            include_usage=include_usage
        )

        return BackupListResponse(
            total=total,
            page=page,
            page_size=page_size,
            backups=backups
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงรายการ Backup: {str(e)}"
        )

@router.get("/{backup_id}", response_model=BackupResponse)
async def get_backup(
    backup_id: str,
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service)
):
    """ดึงข้อมูล Backup ตาม ID"""
    try:
        backup = await backup_svc.get_backup_by_id(backup_id, include_usage=include_usage)
        
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ Backup ที่ต้องการ"
            )
        
        return backup

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงข้อมูล Backup: {str(e)}"
        )

@router.post("/", response_model=BackupCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_backup(
    backup_data: BackupCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service)
):
    """สร้าง Backup ใหม่ (ENGINEER+)"""
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์สร้าง Backup ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        backup = await backup_svc.create_backup(backup_data)
        
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถสร้าง Backup ได้"
            )

        return BackupCreateResponse(
            message="สร้าง Backup สำเร็จ",
            backup=backup
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
            detail=f"เกิดข้อผิดพลาดในการสร้าง Backup: {str(e)}"
        )

@router.put("/{backup_id}", response_model=BackupUpdateResponse)
async def update_backup(
    backup_id: str,
    update_data: BackupUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service)
):
    """อัปเดต Backup (ENGINEER+)"""
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์แก้ไข Backup ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        backup = await backup_svc.update_backup(backup_id, update_data)
        
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถอัปเดต Backup ได้"
            )

        return BackupUpdateResponse(
            message="อัปเดต Backup สำเร็จ",
            backup=backup
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
            detail=f"เกิดข้อผิดพลาดในการอัปเดต Backup: {str(e)}"
        )

@router.delete("/{backup_id}", response_model=BackupDeleteResponse)
async def delete_backup(
    backup_id: str,
    force: bool = Query(False, description="บังคับลบแม้มีการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service)
):
    """ลบ Backup (ADMIN+)"""
    try:
        if force:
            if current_user["role"] != "OWNER":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="การลบแบบบังคับต้องเป็น OWNER เท่านั้น"
                )
        else:
            if current_user["role"] not in ["ADMIN", "OWNER"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="ไม่มีสิทธิ์ลบ Backup ต้องเป็น ADMIN หรือ OWNER"
                )

        success = await backup_svc.delete_backup(backup_id, force=force)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบ Backup ได้"
            )

        return BackupDeleteResponse(
            message="ลบ Backup สำเร็จ"
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
            detail=f"เกิดข้อผิดพลาดในการลบ Backup: {str(e)}"
        )

