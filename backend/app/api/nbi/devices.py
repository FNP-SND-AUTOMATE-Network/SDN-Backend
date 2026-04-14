"""
NBI Device Endpoints
Device listing, detail, and capabilities endpoints
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status
from app.services.device_profile_service_db import DeviceProfileService
from app.core.logging import logger
from app.core.intent_registry import Intents

from .models import ErrorCode, DeviceListResponse, DeviceDetailResponse, LiveConfigResponse
from app.api.users import get_current_user
from app.utils.cache import live_config_cache
from app.services.device_backup_service import DeviceBackupService
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import Depends


router = APIRouter()
device_service = DeviceProfileService()


@router.get("/devices", response_model=DeviceListResponse)
async def list_devices(
    mounted_only: bool = Query(False, description="แสดงเฉพาะ devices ที่ mount ใน ODL"),
    vendor: Optional[str] = Query(None, description="Filter by vendor (cisco, huawei, etc.)"),
):
    """
    Get all registered devices from Database
    
    **Query Parameters:**
    - `mounted_only`: แสดงเฉพาะ devices ที่ mount ใน ODL
    - `vendor`: Filter by vendor (cisco, huawei, juniper, arista)
    
    **Error Codes:**
    - `DATABASE_ERROR`: Database query failed
    """
    try:
        if mounted_only:
            devices = await device_service.list_mounted()
            filter_desc = "mounted devices"
        elif vendor:
            devices = await device_service.list_by_vendor(vendor)
            filter_desc = f"devices with vendor={vendor}"
        else:
            devices = await device_service.list_all()
            filter_desc = "all devices"
        
        device_list = [
            {
                "device_id": d.device_id,
                "node_id": d.node_id,
                "vendor": d.vendor,
                "model": d.model,
                "role": d.role,
                "management_protocol": d.management_protocol,
                "datapath_id": d.datapath_id,
            }
            for d in devices
        ]
        
        return DeviceListResponse(
            success=True,
            code=ErrorCode.SUCCESS.value,
            message=f"Found {len(device_list)} {filter_desc}",
            devices=device_list,
            total=len(device_list),
            source="database"
        )
        
    except Exception as e:
        logger.error(f"Failed to list devices: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": ErrorCode.DATABASE_ERROR.value,
                "message": f"Failed to get device list: {str(e)}"
            }
        )


@router.get("/devices/{device_id}", response_model=DeviceDetailResponse)
async def get_device_info(device_id: str):
    """
    Get detailed information about a specific device
    
    **device_id สามารถเป็น:**
    - node_id (ODL node name)
    - device_name
    - database UUID
    
    **Error Codes:**
    - `DEVICE_NOT_FOUND`: ไม่พบ device
    - `INVALID_DEVICE_ID`: device_id format ไม่ถูกต้อง
    """
    from app.database import get_prisma_client
    
    if not device_id or len(device_id) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.INVALID_DEVICE_ID.value,
                "message": "device_id is required"
            }
        )
    
    try:
        prisma = get_prisma_client()
        
        # Try to find by node_id first
        device = await prisma.devicenetwork.find_first(
            where={"node_id": device_id}
        )
        
        # If not found, try by database ID
        if not device:
            try:
                device = await prisma.devicenetwork.find_unique(
                    where={"id": device_id}
                )
            except Exception:
                pass
        
        # If still not found, try by device_name
        if not device:
            device = await prisma.devicenetwork.find_first(
                where={"device_name": device_id}
            )
        
        if not device:
            raise ValueError(f"Device '{device_id}' not found")
        
        return DeviceDetailResponse(
            success=True,
            code=ErrorCode.SUCCESS.value,
            message="Device found",
            device={
                # === Identity ===
                "id": device.id,
                "serial_number": device.serial_number,
                "device_name": device.device_name,
                "device_model": device.device_model,
                "type": device.type,
                "status": device.status,
                
                # === Network ===
                "ip_address": device.ip_address,
                "mac_address": device.mac_address,
                "description": device.description,
                
                # === NBI/ODL Fields ===
                "node_id": device.node_id,
                "vendor": device.vendor,
                "management_protocol": getattr(device, 'management_protocol', 'NETCONF'),
                "datapath_id": getattr(device, 'datapath_id', None),
                "odl_mounted": device.odl_mounted,
                "odl_connection_status": device.odl_connection_status,
                "last_synced_at": device.last_synced_at.isoformat() if device.last_synced_at else None,
                
                # === NETCONF Connection (ซ่อน password) ===
                "netconf_host": device.netconf_host,
                "netconf_port": device.netconf_port,
                "netconf_username": device.netconf_username,
                "has_netconf_password": bool(device.netconf_password),  # ไม่ส่ง password จริง
                
                # === Ready Status ===
                "ready_to_mount": bool(
                    device.node_id and
                    (device.netconf_host or device.ip_address) and
                    device.netconf_username and
                    device.netconf_password
                ),
                "ready_for_intent": device.odl_mounted and device.odl_connection_status == "CONNECTED",
                
                # === Timestamps ===
                "createdAt": device.createdAt.isoformat() if device.createdAt else None,
                "updatedAt": device.updatedAt.isoformat() if device.updatedAt else None,
            }
        )
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": ErrorCode.DEVICE_NOT_FOUND.value,
                    "message": f"Device '{device_id}' not found",
                    "suggestion": "Use GET /api/v1/nbi/devices to see available devices"
                }
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": ErrorCode.DATABASE_ERROR.value,
                "message": f"Failed to get device: {str(e)}"
            }
        )


@router.get("/devices/{device_id}/capabilities")
async def get_device_capabilities(device_id: str):
    """
    Get intent capabilities for a specific device
    
    Get intent capabilities for a specific device.
    
    (Note: OpenConfig support has been removed. All intents are now vendor-specific)
    
    **Error Codes:**
    - `DEVICE_NOT_FOUND`: ไม่พบ device
    """
    try:
        device = await device_service.get(device_id)
        
        # All intents are vendor-only (OpenConfig removed)
        # Vendor only: all intents starting with INTERFACE, ROUTING, SYSTEM, VLAN
        vendor_only = [
            Intents.INTERFACE.SET_IPV4, Intents.INTERFACE.SET_IPV6, 
            Intents.INTERFACE.ENABLE, Intents.INTERFACE.DISABLE,
            Intents.INTERFACE.SET_DESCRIPTION, Intents.INTERFACE.SET_MTU,
            Intents.SHOW.INTERFACE, Intents.SHOW.INTERFACES,
            Intents.SHOW.IP_ROUTE, Intents.SHOW.IP_INTERFACE_BRIEF,
            Intents.SHOW.VERSION, Intents.SHOW.RUNNING_CONFIG,
            Intents.ROUTING.STATIC_ADD, Intents.ROUTING.STATIC_DELETE,
            Intents.VLAN.CREATE, Intents.VLAN.DELETE, Intents.SHOW.VLANS
        ]
        
        return {
            "success": True,
            "code": ErrorCode.SUCCESS.value,
            "message": "Capabilities retrieved",
            "data": {
                "device_id": device_id,
                "node_id": device.node_id,
                "vendor": device.vendor,
                "vendor_only": vendor_only,
                "total_intents": len(vendor_only)
            }
        }
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": ErrorCode.DEVICE_NOT_FOUND.value,
                    "message": f"Device '{device_id}' not found"
                }
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": ErrorCode.DATABASE_ERROR.value,
                "message": f"Failed to get capabilities: {str(e)}"
            }
        )

@router.get("/devices/{device_id}/live-config", response_model=LiveConfigResponse)
async def get_device_live_config(
    device_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get live running configuration directly from the device via CLI.
    Includes an In-Memory TTL cache (default 60s) to prevent device overload.
    """
    from app.database import get_prisma_client
    
    # 1. Check Cache
    cache_key = f"live_config_{device_id}"
    cached_data = live_config_cache.get(cache_key)
    if cached_data:
        return LiveConfigResponse(
            success=True,
            code=ErrorCode.SUCCESS.value,
            message="Fetched from cache",
            config=cached_data["config"],
            cached=True,
            fetched_at=cached_data["timestamp"]
        )
        
    # 2. Fetch from device
    try:
        user_id = current_user["id"]
        prisma = get_prisma_client()
        backup_service = DeviceBackupService(prisma)
        
        config_text = await backup_service.get_live_running_config(
            device_id=device_id,
            user_id=user_id
        )
        
        timestamp = datetime.now().isoformat()
        
        # 3. Save to Cache
        live_config_cache.set(cache_key, {
            "config": config_text,
            "timestamp": timestamp
        })
        
        return LiveConfigResponse(
            success=True,
            code=ErrorCode.SUCCESS.value,
            message="Fetched from device directly",
            config=config_text,
            cached=False,
            fetched_at=timestamp
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.INVALID_PARAMS.value,
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Live config fetch failed for {device_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DEVICE_CONNECTION_FAILED",
                "message": f"Could not fetch live config: {str(e)}"
            }
        )

