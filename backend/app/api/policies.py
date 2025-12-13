from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.policy_service import PolicyService
from app.models.policy import (
    PolicyCreate,
    PolicyUpdate,
    PolicyResponse,
    PolicyListResponse,
    PolicyCreateResponse,
    PolicyUpdateResponse,
    PolicyDeleteResponse
)
from prisma import Prisma

router = APIRouter(prefix="/policies", tags=["Policies"])

def get_policy_service(db: Prisma = Depends(get_db)) -> PolicyService:
    """Get PolicyService instance"""
    return PolicyService(db)

@router.get("/", response_model=PolicyListResponse)
async def get_policies(
    page: int = Query(1, ge=1, description="หน้าที่ต้องการ"),
    page_size: int = Query(20, ge=1, le=100, description="จำนวนรายการต่อหน้า"),
    search: Optional[str] = Query(None, description="ค้นหาจาก policy_name, description"),
    parent_policy_id: Optional[str] = Query(None, description="กรองตาม Parent Policy ID"),
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    policy_svc: PolicyService = Depends(get_policy_service)
):
    """
    ดึงรายการ Policy ทั้งหมด
    
    - รองรับ pagination
    - รองรับการค้นหา
    - รองรับ hierarchy (parent-child)
    - แสดงผู้สร้าง Policy
    - ต้องเป็น authenticated user
    """
    try:
        policies, total = await policy_svc.get_policies(
            page=page,
            page_size=page_size,
            search=search,
            parent_policy_id=parent_policy_id,
            include_usage=include_usage
        )

        return PolicyListResponse(
            total=total,
            page=page,
            page_size=page_size,
            policies=policies
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงรายการ Policy: {str(e)}"
        )

@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: str,
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    policy_svc: PolicyService = Depends(get_policy_service)
):
    """
    ดึงข้อมูล Policy ตาม ID
    
    - แสดงจำนวนการใช้งาน
    - แสดง Parent Policy
    - แสดงผู้สร้าง
    - ต้องเป็น authenticated user
    """
    try:
        policy = await policy_svc.get_policy_by_id(policy_id, include_usage=include_usage)
        
        if not policy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ Policy ที่ต้องการ"
            )
        
        return policy

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงข้อมูล Policy: {str(e)}"
        )

@router.post("/", response_model=PolicyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    policy_data: PolicyCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    policy_svc: PolicyService = Depends(get_policy_service)
):
    """
    สร้าง Policy ใหม่
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - policy_name ต้องไม่ซ้ำ
    - สามารถกำหนด Parent Policy ได้ (hierarchy)
    """
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์สร้าง Policy ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        policy = await policy_svc.create_policy(policy_data, current_user["id"])
        
        if not policy:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถสร้าง Policy ได้"
            )

        return PolicyCreateResponse(
            message="สร้าง Policy สำเร็จ",
            policy=policy
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
            detail=f"เกิดข้อผิดพลาดในการสร้าง Policy: {str(e)}"
        )

@router.put("/{policy_id}", response_model=PolicyUpdateResponse)
async def update_policy(
    policy_id: str,
    update_data: PolicyUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    policy_svc: PolicyService = Depends(get_policy_service)
):
    """
    อัปเดต Policy
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - สามารถเปลี่ยน Parent Policy ได้
    """
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์แก้ไข Policy ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        policy = await policy_svc.update_policy(policy_id, update_data)
        
        if not policy:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถอัปเดต Policy ได้"
            )

        return PolicyUpdateResponse(
            message="อัปเดต Policy สำเร็จ",
            policy=policy
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
            detail=f"เกิดข้อผิดพลาดในการอัปเดต Policy: {str(e)}"
        )

@router.delete("/{policy_id}", response_model=PolicyDeleteResponse)
async def delete_policy(
    policy_id: str,
    force: bool = Query(False, description="บังคับลบแม้มีการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    policy_svc: PolicyService = Depends(get_policy_service)
):
    """
    ลบ Policy
    
    - ต้องเป็น ADMIN หรือ OWNER
    - ไม่สามารถลบถ้ามีการใช้งานอยู่ (ยกเว้น force=true)
    - force=true ต้องเป็น OWNER เท่านั้น
    """
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
                    detail="ไม่มีสิทธิ์ลบ Policy ต้องเป็น ADMIN หรือ OWNER"
                )

        success = await policy_svc.delete_policy(policy_id, force=force)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบ Policy ได้"
            )

        return PolicyDeleteResponse(
            message="ลบ Policy สำเร็จ"
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
            detail=f"เกิดข้อผิดพลาดในการลบ Policy: {str(e)}"
        )

