from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.device_network_service import DeviceNetworkService
from app.models.device_network import (
    DeviceNetworkCreate,
    DeviceNetworkUpdate,
    DeviceNetworkResponse,
    DeviceNetworkListResponse,
    DeviceNetworkCreateResponse,
    DeviceNetworkUpdateResponse,
    DeviceNetworkDeleteResponse,
    TypeDevice,
    StatusDevice,
    DeviceTagAssignment
)
from prisma import Prisma
from app.core.constants import ALLOWED_ROLES
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/device-networks", tags=["Device Networks"])

def get_device_service(db: Prisma = Depends(get_db)) -> DeviceNetworkService:
    """Get DeviceNetworkService instance"""
    return DeviceNetworkService(db)

@router.get("/", response_model=DeviceNetworkListResponse)
async def get_devices(
    page: int = Query(1, ge=1, description="หน้าที่ต้องการ"),
    page_size: int = Query(20, ge=1, le=100, description="จำนวนรายการต่อหน้า"),
    device_type: Optional[str] = Query(None, description="กรองตามประเภทอุปกรณ์"),
    status: Optional[str] = Query(None, description="กรองตามสถานะ"),
    search: Optional[str] = Query(None, description="ค้นหาจาก device_name, model, serial, IP"),
    os_id: Optional[str] = Query(None, description="กรองตาม OS ID"),
    local_site_id: Optional[str] = Query(None, description="กรองตาม Local Site ID"),
    policy_id: Optional[str] = Query(None, description="กรองตาม Policy ID"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service)
):
    """
    ดึงรายการ Device Network ทั้งหมด
    
    - รองรับ pagination
    - รองรับ filter หลายแบบ (type, status, os, tag, site, policy)
    - รองรับการค้นหา
    - แสดงข้อมูลที่เชื่อมโยงทั้งหมด
    - ต้องเป็น authenticated user
    """
    try:
        devices, total = await device_svc.get_devices(
            page=page,
            page_size=page_size,
            device_type=device_type,
            status=status,
            search=search,
            os_id=os_id,
            local_site_id=local_site_id,
            policy_id=policy_id
        )

        return DeviceNetworkListResponse(
            total=total,
            page=page,
            page_size=page_size,
            devices=devices
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงรายการ Device Network: {str(e)}"
        )

@router.get("/{device_id}", response_model=DeviceNetworkResponse)
async def get_device(
    device_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service)
):
    """
    ดึงข้อมูล Device Network ตาม ID
    
    - แสดงข้อมูลที่เชื่อมโยงทั้งหมด
    - ต้องเป็น authenticated user
    """
    try:
        device = await device_svc.get_device_by_id(device_id)
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ Device Network ที่ต้องการ"
            )
        
        return device

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงข้อมูล Device Network: {str(e)}"
        )

@router.post("/", response_model=DeviceNetworkCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_device(
    device_data: DeviceNetworkCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service)
):
    """
    สร้าง Device Network ใหม่
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - serial_number และ mac_address ต้องไม่ซ้ำ
    - foreign keys ทั้งหมดเป็น optional
    """
    try:
        if current_user["role"] not in ALLOWED_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"ไม่มีสิทธิ์สร้าง Device Network ต้องเป็น {', '.join(ALLOWED_ROLES)}"
            )

        device = await device_svc.create_device(device_data)
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถสร้าง Device Network ได้"
            )

        return DeviceNetworkCreateResponse(
            message="สร้าง Device Network สำเร็จ",
            device=device
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
            detail=f"เกิดข้อผิดพลาดในการสร้าง Device Network: {str(e)}"
        )

@router.put("/{device_id}", response_model=DeviceNetworkUpdateResponse)
async def update_device(
    device_id: str,
    update_data: DeviceNetworkUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service)
):
    """
    อัปเดต Device Network
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - สามารถอัปเดตบางฟิลด์ได้
    - สามารถเปลี่ยน foreign keys ได้
    """
    try:
        if current_user["role"] not in ALLOWED_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"ไม่มีสิทธิ์แก้ไข Device Network ต้องเป็น {', '.join(ALLOWED_ROLES)}"
            )

        device = await device_svc.update_device(device_id, update_data)
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถอัปเดต Device Network ได้"
            )

        return DeviceNetworkUpdateResponse(
            message="อัปเดต Device Network สำเร็จ",
            device=device
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
            detail=f"เกิดข้อผิดพลาดในการอัปเดต Device Network: {str(e)}"
        )

@router.delete("/{device_id}", response_model=DeviceNetworkDeleteResponse)
async def delete_device(
    device_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service)
):
    """
    ลบ Device Network
    
    - ต้องเป็น ADMIN หรือ OWNER
    """
    try:
        if current_user["role"] not in ["ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์ลบ Device Network ต้องเป็น ADMIN หรือ OWNER"
            )

        success = await device_svc.delete_device(device_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบ Device Network ได้"
            )

        return DeviceNetworkDeleteResponse(
            message="ลบ Device Network สำเร็จ"
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
            detail=f"เกิดข้อผิดพลาดในการลบ Device Network: {str(e)}"
        )

# ========= Tag Management Endpoints =========

@router.post("/{device_id}/tags", response_model=DeviceNetworkUpdateResponse)
async def assign_tags_to_device(
    device_id: str,
    tag_assignment: DeviceTagAssignment,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service)
):
    """
    เพิ่ม Tags ให้กับ Device
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - สามารถเพิ่มหลาย tags พร้อมกันได้
    """
    try:
        if current_user["role"] not in ALLOWED_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"ไม่มีสิทธิ์จัดการ Tags ต้องเป็น {', '.join(ALLOWED_ROLES)}"
            )

        device = await device_svc.assign_tags(device_id, tag_assignment.tag_ids)
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถเพิ่ม Tags ได้"
            )

        return DeviceNetworkUpdateResponse(
            message=f"เพิ่ม {len(tag_assignment.tag_ids)} Tags สำเร็จ",
            device=device
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

@router.delete("/{device_id}/tags", response_model=DeviceNetworkUpdateResponse)
async def remove_tags_from_device(
    device_id: str,
    tag_assignment: DeviceTagAssignment,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service)
):
    """
    ลบ Tags ออกจาก Device
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - สามารถลบหลาย tags พร้อมกันได้
    """
    try:
        if current_user["role"] not in ALLOWED_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"ไม่มีสิทธิ์จัดการ Tags ต้องเป็น {', '.join(ALLOWED_ROLES)}"
            )

        device = await device_svc.remove_tags(device_id, tag_assignment.tag_ids)
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบ Tags ได้"
            )

        return DeviceNetworkUpdateResponse(
            message=f"ลบ {len(tag_assignment.tag_ids)} Tags สำเร็จ",
            device=device
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

