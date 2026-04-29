from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user, check_engineer_permission
from app.services.device_network_service import DeviceNetworkService
from app.services.audit_service import AuditService
from app.models.audit import AuditAction
from app.services.odl_sync_service import OdlSyncService
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
from app.utils.request_helpers import get_client_ip, get_user_agent
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/device-networks", tags=["Device Networks"])

def get_device_service(db: Prisma = Depends(get_db)) -> DeviceNetworkService:
    return DeviceNetworkService(db)

def get_audit_service(db: Prisma = Depends(get_db)) -> AuditService:
    return AuditService(db)

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
            detail=f"Error getting device list: {str(e)}"
        )

@router.get("/{device_id}", response_model=DeviceNetworkResponse)
async def get_device(
    device_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service)
):
    try:
        device = await device_svc.get_device_by_id(device_id)
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found"
            )
        
        return device

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting device: {str(e)}"
        )

@router.post("/", response_model=DeviceNetworkCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_device(
    request: Request,
    device_data: DeviceNetworkCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        # Require ENGINEER or ADMIN
        check_engineer_permission(current_user)

        device, ipam_notifications = await device_svc.create_device(device_data)
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error creating device"
            )

        try:
            client_ip = get_client_ip(request)
            user_agent = get_user_agent(request)
                
            await audit_svc.create_device_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.DEVICE_CREATE,
                device_id=device.id,
                device_name=device.device_name,
                changes=device_data.dict(exclude_unset=True),
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return DeviceNetworkCreateResponse(
            message="Device created successfully",
            device=device,
            ipam_notifications=ipam_notifications
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
            detail=f"Error creating device: {str(e)}"
        )

@router.put("/{device_id}", response_model=DeviceNetworkUpdateResponse)
async def update_device(
    request: Request,
    device_id: str,
    update_data: DeviceNetworkUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        # Require ENGINEER or ADMIN
        check_engineer_permission(current_user)

        device, ipam_notifications = await device_svc.update_device(device_id, update_data)
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error updating device"
            )

        try:
            client_ip = get_client_ip(request)
            user_agent = get_user_agent(request)
                
            await audit_svc.create_device_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.DEVICE_UPDATE,
                device_id=device.id,
                device_name=device.device_name,
                changes=update_data.dict(exclude_unset=True),
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return DeviceNetworkUpdateResponse(
            message="Device updated successfully",
            device=device,
            ipam_notifications=ipam_notifications
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
            detail=f"Error updating device: {str(e)}"
        )

@router.delete("/{device_id}", response_model=DeviceNetworkDeleteResponse)
async def delete_device(
    request: Request,
    device_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        if current_user["role"] not in ["ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User role {current_user['role']} is not allowed to delete device"
            )
            
        old_device = await device_svc.get_device_by_id(device_id)
        if not old_device:
            raise HTTPException(status_code=404, detail="Device not found")

        success, ipam_notifications = await device_svc.delete_device(device_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error deleting device"
            )

        try:
            client_ip = get_client_ip(request)
            user_agent = get_user_agent(request)
                
            await audit_svc.create_device_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.DEVICE_DELETE,
                device_id=device_id,
                device_name=old_device.device_name,
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return DeviceNetworkDeleteResponse(
            message="Device deleted successfully",
            ipam_notifications=ipam_notifications
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
            detail=f"Error deleting device: {str(e)}"
        )

# ========= Tag Management Endpoints =========

@router.post("/{device_id}/tags", response_model=DeviceNetworkUpdateResponse)
async def assign_tags_to_device(
    device_id: str,
    tag_assignment: DeviceTagAssignment,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service)
):
    try:
        # Require ENGINEER or ADMIN
        check_engineer_permission(current_user)

        device = await device_svc.assign_tags(device_id, tag_assignment.tag_ids)
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error assigning tags to device"
            )

        return DeviceNetworkUpdateResponse(
            message=f"Assign {len(tag_assignment.tag_ids)} tags to device successfully",
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
            detail=f"Error assigning tags to device: {str(e)}"
        )


@router.delete("/{device_id}/tags", response_model=DeviceNetworkUpdateResponse)
async def remove_tags_from_device(
    device_id: str,
    tag_assignment: DeviceTagAssignment,
    current_user: Dict[str, Any] = Depends(get_current_user),
    device_svc: DeviceNetworkService = Depends(get_device_service)
):
    try:
        # Require ENGINEER or ADMIN
        check_engineer_permission(current_user)

        device = await device_svc.remove_tags(device_id, tag_assignment.tag_ids)
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error removing tags from device"
            )

        return DeviceNetworkUpdateResponse(
            message=f"Remove {len(tag_assignment.tag_ids)} tags from device successfully",
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
            detail=f"Error removing tags from device: {str(e)}"
        )

