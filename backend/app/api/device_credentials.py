from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any
from app.database import get_db
from app.api.users import get_current_user
from app.services.device_credentials_service import DeviceCredentialsService
from app.models.device_credentials import (
    DeviceCredentialsCreate,
    DeviceCredentialsUpdate,
    DeviceCredentialsResponse,
    DeviceCredentialsCreateResponse,
    DeviceCredentialsUpdateResponse,
    DeviceCredentialsDeleteResponse
)

router = APIRouter(prefix="/device-credentials", tags=["Device Network Credentials"])


@router.get(
    "/",
    response_model=DeviceCredentialsResponse,
    summary="ดึงข้อมูล Device Network Credentials",
    description="ดึงข้อมูล Device Network Credentials ของผู้ใช้ปัจจุบัน (ไม่แสดงรหัสผ่าน แต่แสดงว่ามีหรือไม่)"
)
async def get_device_credentials(
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """ดึงข้อมูล Device Network Credentials ของผู้ใช้ปัจจุบัน"""
    try:
        device_creds_svc = DeviceCredentialsService(db)
        
        device_credentials = await device_creds_svc.get_device_credentials(current_user["id"])
        
        if not device_credentials:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ Device Network Credentials กรุณาสร้างใหม่"
            )
        
        return device_credentials
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_device_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="เกิดข้อผิดพลาดในการดึงข้อมูล Device Network Credentials"
        )


@router.post(
    "/",
    response_model=DeviceCredentialsCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="สร้าง Device Network Credentials ใหม่",
    description="สร้าง Device Network Credentials ใหม่สำหรับผู้ใช้ปัจจุบัน"
)
async def create_device_credentials(
    data: DeviceCredentialsCreate,
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """สร้าง Device Network Credentials ใหม่"""
    try:
        device_creds_svc = DeviceCredentialsService(db)
        
        device_credentials = await device_creds_svc.create_device_credentials(
            user_id=current_user["id"],
            data=data
        )
        
        if not device_credentials:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถสร้าง Device Network Credentials ได้"
            )
        
        return DeviceCredentialsCreateResponse(
            message="สร้าง Device Network Credentials สำเร็จ",
            device_credentials=device_credentials
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in create_device_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="เกิดข้อผิดพลาดในการสร้าง Device Network Credentials"
        )


@router.put(
    "/",
    response_model=DeviceCredentialsUpdateResponse,
    summary="อัปเดต Device Network Credentials",
    description="อัปเดต Device Network Credentials ของผู้ใช้ปัจจุบัน"
)
async def update_device_credentials(
    data: DeviceCredentialsUpdate,
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """อัปเดต Device Network Credentials"""
    try:
        device_creds_svc = DeviceCredentialsService(db)
        
        device_credentials = await device_creds_svc.update_device_credentials(
            user_id=current_user["id"],
            data=data
        )
        
        if not device_credentials:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถอัปเดต Device Network Credentials ได้"
            )
        
        return DeviceCredentialsUpdateResponse(
            message="อัปเดต Device Network Credentials สำเร็จ",
            device_credentials=device_credentials
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in update_device_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="เกิดข้อผิดพลาดในการอัปเดต Device Network Credentials"
        )


@router.delete(
    "/",
    response_model=DeviceCredentialsDeleteResponse,
    summary="ลบ Device Network Credentials",
    description="ลบ Device Network Credentials ของผู้ใช้ปัจจุบัน"
)
async def delete_device_credentials(
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """ลบ Device Network Credentials"""
    try:
        device_creds_svc = DeviceCredentialsService(db)
        
        success = await device_creds_svc.delete_device_credentials(current_user["id"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบ Device Network Credentials ได้"
            )
        
        return DeviceCredentialsDeleteResponse(
            message="ลบ Device Network Credentials สำเร็จ"
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in delete_device_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="เกิดข้อผิดพลาดในการลบ Device Network Credentials"
        )


@router.post(
    "/verify",
    summary="ตรวจสอบ Device Network Credentials",
    description="ตรวจสอบความถูกต้องของ Device Network Credentials สำหรับการเข้าใช้งานอุปกรณ์"
)
async def verify_device_credentials(
    credentials: Dict[str, str],
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """ตรวจสอบ Device Network Credentials"""
    try:
        # ตรวจสอบ input
        if "username" not in credentials or "password" not in credentials:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="กรุณาระบุ username และ password"
            )
        
        device_creds_svc = DeviceCredentialsService(db)
        
        is_valid = await device_creds_svc.verify_device_credentials(
            user_id=current_user["id"],
            username=credentials["username"],
            password=credentials["password"]
        )
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Device Network Credentials ไม่ถูกต้อง"
            )
        
        return {
            "message": "Device Network Credentials ถูกต้อง",
            "valid": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in verify_device_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="เกิดข้อผิดพลาดในการตรวจสอบ Device Network Credentials"
        )
