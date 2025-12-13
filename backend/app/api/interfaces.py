from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, Optional, List
from app.database import get_db
from app.api.users import get_current_user
from app.services.interface_service import InterfaceService
from app.models.interface import (
    InterfaceCreate,
    InterfaceUpdate,
    InterfaceResponse,
    InterfaceListResponse,
    InterfaceCreateResponse,
    InterfaceUpdateResponse,
    InterfaceDeleteResponse,
    InterfaceStatus,
    InterfaceType
)
from prisma import Prisma

router = APIRouter(prefix="/interfaces", tags=["Network Interfaces"])

def get_interface_service(db: Prisma = Depends(get_db)) -> InterfaceService:
    """Get InterfaceService instance"""
    return InterfaceService(db)

@router.get("/", response_model=InterfaceListResponse)
async def get_interfaces(
    page: int = Query(1, ge=1, description="หน้าที่ต้องการ"),
    page_size: int = Query(20, ge=1, le=100, description="จำนวนรายการต่อหน้า"),
    device_id: Optional[str] = Query(None, description="กรองตาม Device ID"),
    status: Optional[str] = Query(None, description="กรองตามสถานะ"),
    interface_type: Optional[str] = Query(None, description="กรองตามประเภท Interface"),
    search: Optional[str] = Query(None, description="ค้นหาจาก name, label, description"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    """
    ดึงรายการ Interface ทั้งหมด
    
    - รองรับ pagination
    - รองรับ filter ตาม device, status, type
    - รองรับการค้นหา
    - แสดงข้อมูล Device ที่เชื่อมโยง
    - ต้องเป็น authenticated user
    """
    try:
        interfaces, total = await interface_svc.get_interfaces(
            page=page,
            page_size=page_size,
            device_id=device_id,
            status=status,
            interface_type=interface_type,
            search=search
        )

        return InterfaceListResponse(
            total=total,
            page=page,
            page_size=page_size,
            interfaces=interfaces
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงรายการ Interface: {str(e)}"
        )

@router.get("/device/{device_id}", response_model=List[InterfaceResponse])
async def get_interfaces_by_device(
    device_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    """
    ดึงรายการ Interface ทั้งหมดของ Device
    
    - แสดง Interface ทั้งหมดของ Device นี้
    - เรียงตามชื่อ Interface
    - ต้องเป็น authenticated user
    """
    try:
        interfaces = await interface_svc.get_interfaces_by_device(device_id)
        return interfaces

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงรายการ Interface: {str(e)}"
        )

@router.get("/{interface_id}", response_model=InterfaceResponse)
async def get_interface(
    interface_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    """
    ดึงข้อมูล Interface ตาม ID
    
    - แสดงข้อมูล Device ที่เชื่อมโยง
    - ต้องเป็น authenticated user
    """
    try:
        interface = await interface_svc.get_interface_by_id(interface_id)
        
        if not interface:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ Interface ที่ต้องการ"
            )
        
        return interface

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงข้อมูล Interface: {str(e)}"
        )

@router.post("/", response_model=InterfaceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_interface(
    interface_data: InterfaceCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    """
    สร้าง Interface ใหม่
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - Interface name ต้องไม่ซ้ำใน Device เดียวกัน
    """
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์สร้าง Interface ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        interface = await interface_svc.create_interface(interface_data)
        
        if not interface:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถสร้าง Interface ได้"
            )

        return InterfaceCreateResponse(
            message="สร้าง Interface สำเร็จ",
            interface=interface
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
            detail=f"เกิดข้อผิดพลาดในการสร้าง Interface: {str(e)}"
        )

@router.put("/{interface_id}", response_model=InterfaceUpdateResponse)
async def update_interface(
    interface_id: str,
    update_data: InterfaceUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    """
    อัปเดต Interface
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    - สามารถอัปเดตบางฟิลด์ได้
    """
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์แก้ไข Interface ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        interface = await interface_svc.update_interface(interface_id, update_data)
        
        if not interface:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถอัปเดต Interface ได้"
            )

        return InterfaceUpdateResponse(
            message="อัปเดต Interface สำเร็จ",
            interface=interface
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
            detail=f"เกิดข้อผิดพลาดในการอัปเดต Interface: {str(e)}"
        )

@router.delete("/{interface_id}", response_model=InterfaceDeleteResponse)
async def delete_interface(
    interface_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    """
    ลบ Interface
    
    - ต้องเป็น ENGINEER, ADMIN หรือ OWNER
    """
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์ลบ Interface ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        success = await interface_svc.delete_interface(interface_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบ Interface ได้"
            )

        return InterfaceDeleteResponse(
            message="ลบ Interface สำเร็จ"
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
            detail=f"เกิดข้อผิดพลาดในการลบ Interface: {str(e)}"
        )

