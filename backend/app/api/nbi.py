"""
NBI (Northbound Interface) API
Intent-Based API สำหรับ Network Operations

Flow:
1. สร้าง Device ใน DB (พร้อม node_id และ NETCONF credentials)
2. Mount Device ใน ODL ผ่าน API
3. Check/Sync Connection Status
4. ใช้งาน Intent API

Error Codes สำหรับ Frontend:
- 200: Success
- 400: Bad Request (ข้อมูลไม่ครบ/ไม่ถูกต้อง)
- 401: Unauthorized (ยังไม่ได้ login)
- 403: Forbidden (ไม่มีสิทธิ์)
- 404: Not Found (ไม่พบ device/intent)
- 409: Conflict (device already mounted, etc.)
- 422: Validation Error (ข้อมูลไม่ผ่าน validation)
- 502: Bad Gateway (ODL connection failed)
- 503: Service Unavailable (ODL not available)
- 504: Gateway Timeout (ODL timeout)
"""
from typing import Dict, List, Any, Optional
from enum import Enum
import re
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from app.schemas.intent import IntentRequest, IntentResponse
from app.services.intent_service import IntentService
from app.services.device_profile_service_db import DeviceProfileService
from app.services.odl_sync_service import OdlSyncService
from app.services.odl_mount_service import OdlMountService
from app.core.intent_registry import IntentRegistry
from app.core.logging import logger
from app.core.errors import DeviceNotMounted
import asyncio


router = APIRouter(prefix="/api/v1/nbi", tags=["NBI"])
intent_service = IntentService()
device_service = DeviceProfileService()
odl_sync_service = OdlSyncService()
odl_mount_service = OdlMountService()


# ===== Error Codes Enum =====

class ErrorCode(str, Enum):
    """Error codes สำหรับ Frontend"""
    # Success
    SUCCESS = "SUCCESS"
    
    # 400 Bad Request
    MISSING_NODE_ID = "MISSING_NODE_ID"
    MISSING_NETCONF_HOST = "MISSING_NETCONF_HOST"
    MISSING_NETCONF_CREDENTIALS = "MISSING_NETCONF_CREDENTIALS"
    INVALID_DEVICE_ID = "INVALID_DEVICE_ID"
    INVALID_INTENT = "INVALID_INTENT"
    INVALID_PARAMS = "INVALID_PARAMS"
    INVALID_VENDOR = "INVALID_VENDOR"
    
    # 404 Not Found
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    INTENT_NOT_FOUND = "INTENT_NOT_FOUND"
    NODE_NOT_FOUND_IN_ODL = "NODE_NOT_FOUND_IN_ODL"
    
    # 409 Conflict
    DEVICE_ALREADY_MOUNTED = "DEVICE_ALREADY_MOUNTED"
    DEVICE_NOT_MOUNTED = "DEVICE_NOT_MOUNTED"
    DEVICE_ALREADY_EXISTS = "DEVICE_ALREADY_EXISTS"
    
    # 502 Bad Gateway
    ODL_CONNECTION_FAILED = "ODL_CONNECTION_FAILED"
    ODL_REQUEST_FAILED = "ODL_REQUEST_FAILED"
    ODL_MOUNT_FAILED = "ODL_MOUNT_FAILED"
    ODL_UNMOUNT_FAILED = "ODL_UNMOUNT_FAILED"
    
    # 503 Service Unavailable
    ODL_NOT_AVAILABLE = "ODL_NOT_AVAILABLE"
    DATABASE_ERROR = "DATABASE_ERROR"
    
    # 504 Gateway Timeout
    ODL_TIMEOUT = "ODL_TIMEOUT"
    MOUNT_TIMEOUT = "MOUNT_TIMEOUT"
    
    # Device Status
    DEVICE_NOT_CONNECTED = "DEVICE_NOT_CONNECTED"
    DEVICE_CONNECTING = "DEVICE_CONNECTING"


# ===== Base Response Models =====

class APIResponse(BaseModel):
    """Base response สำหรับทุก API"""
    success: bool
    code: str  # ErrorCode enum value
    message: str
    data: Optional[Dict[str, Any]] = None


class MountRequest(BaseModel):
    """Request body สำหรับ mount device"""
    wait_for_connection: bool = Field(
        default=True, 
        description="รอจนกว่าจะ connected (max 30s)"
    )
    max_wait_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="เวลารอสูงสุด (วินาที) - 5 ถึง 120"
    )


class MountResponse(BaseModel):
    """Response สำหรับ mount operations"""
    success: bool
    code: str
    message: str
    node_id: Optional[str] = None
    connection_status: Optional[str] = None
    device_status: Optional[str] = None
    ready_for_intent: bool = False
    data: Optional[Dict[str, Any]] = None


class SyncResponse(BaseModel):
    """Response สำหรับ sync operations"""
    success: bool
    code: str
    message: str
    data: Optional[Dict[str, Any]] = None


class DeviceListResponse(BaseModel):
    """Response สำหรับ list devices"""
    success: bool
    code: str
    message: str
    devices: List[Dict[str, Any]]
    total: int
    source: str


class DeviceDetailResponse(BaseModel):
    """Response สำหรับ device detail"""
    success: bool
    code: str
    message: str
    device: Optional[Dict[str, Any]] = None


class IntentListResponse(BaseModel):
    """Response สำหรับ list intents"""
    success: bool
    code: str
    message: str
    intents: Dict[str, List[str]]


class AutoCreateRequest(BaseModel):
    """Request body สำหรับ auto-create device จาก ODL"""
    node_id: str = Field(..., min_length=1, description="ODL node-id")
    vendor: str = Field(default="cisco", description="Vendor: cisco, huawei, juniper, arista")
    
    @validator('vendor')
    def validate_vendor(cls, v):
        valid_vendors = ['cisco', 'huawei', 'juniper', 'arista', 'other']
        if v.lower() not in valid_vendors:
            raise ValueError(f"Invalid vendor. Must be one of: {', '.join(valid_vendors)}")
        return v.lower()


class UpdateNetconfRequest(BaseModel):
    """Request body สำหรับ update NETCONF credentials"""
    netconf_host: Optional[str] = Field(None, description="IP/Hostname สำหรับ NETCONF")
    netconf_port: int = Field(default=830, description="NETCONF port")
    netconf_username: Optional[str] = Field(None, description="Username สำหรับ NETCONF")
    netconf_password: Optional[str] = Field(None, description="Password สำหรับ NETCONF")
    vendor: Optional[str] = Field(None, description="Vendor: cisco, huawei, juniper, arista")


# ===== Helper Functions =====

def create_error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    """สร้าง error response แบบ consistent"""
    content = {
        "success": False,
        "code": code.value,
        "message": message,
        "data": details
    }
    return JSONResponse(status_code=status_code, content=content)


def create_success_response(
    message: str,
    data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """สร้าง success response แบบ consistent"""
    return {
        "success": True,
        "code": ErrorCode.SUCCESS.value,
        "message": message,
        "data": data
    }


# ===== Intent Endpoints =====

@router.post("/intent", response_model=IntentResponse)
async def handle_intent(req: IntentRequest):
    """
    Execute an Intent-based network operation
    
    **Error Codes:**
    - `INTENT_NOT_FOUND`: Intent ไม่มีในระบบ
    - `DEVICE_NOT_FOUND`: ไม่พบ device
    - `DEVICE_NOT_CONNECTED`: Device ยังไม่ connected
    - `INVALID_PARAMS`: Parameters ไม่ถูกต้อง
    - `ODL_REQUEST_FAILED`: ODL request failed
    
    **Example Request:**
    ```json
    {
        "intent": "show.interface",
        "deviceId": "CSR1",
        "params": {
            "interface": "GigabitEthernet1"
        }
    }
    ```
    """
    try:
        # Validate intent exists
        intent = IntentRegistry.get(req.intent)
        if not intent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": ErrorCode.INTENT_NOT_FOUND.value,
                    "message": f"Intent '{req.intent}' not found",
                    "available_intents": list(IntentRegistry.get_supported_intents().keys())
                }
            )
        
        # Execute intent
        return await intent_service.handle(req)
    
    except DeviceNotMounted as e:
        # Handle DeviceNotMounted error specifically
        detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.DEVICE_NOT_MOUNTED.value,
                "message": detail.get("message", "Device is not mounted"),
                "suggestion": detail.get("suggestion", f"Use POST /api/v1/nbi/devices/{req.deviceId}/mount to mount the device first")
            }
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        error_msg = str(e)
        # Determine error code based on message
        if "not found" in error_msg.lower():
            code = ErrorCode.DEVICE_NOT_FOUND
            status_code = status.HTTP_404_NOT_FOUND
        elif "not connected" in error_msg.lower() or "mount point" in error_msg.lower():
            code = ErrorCode.DEVICE_NOT_CONNECTED
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            code = ErrorCode.INVALID_PARAMS
            status_code = status.HTTP_400_BAD_REQUEST
        
        raise HTTPException(status_code=status_code, detail={
            "code": code.value,
            "message": error_msg
        })
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": ErrorCode.ODL_TIMEOUT.value,
                "message": "ODL request timeout"
            }
        )
    except Exception as e:
        logger.error(f"Intent execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_REQUEST_FAILED.value,
                "message": f"Intent execution failed: {str(e)}"
            }
        )


# ===== Discovery Endpoints =====

@router.get("/intents", response_model=IntentListResponse)
async def list_supported_intents():
    """
    Get all supported intents grouped by category
    
    **Always returns 200**
    """
    try:
        intents = IntentRegistry.get_supported_intents()
        return IntentListResponse(
            success=True,
            code=ErrorCode.SUCCESS.value,
            message=f"Found {sum(len(v) for v in intents.values())} intents",
            intents=intents
        )
    except Exception as e:
        logger.error(f"Failed to get intents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ErrorCode.DATABASE_ERROR.value,
                "message": "Failed to get intent list"
            }
        )


@router.get("/intents/{intent_name}")
async def get_intent_info(intent_name: str):
    """
    Get detailed information about a specific intent
    
    **Error Codes:**
    - `INTENT_NOT_FOUND`: Intent ไม่มีในระบบ
    """
    intent = IntentRegistry.get(intent_name)
    if not intent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ErrorCode.INTENT_NOT_FOUND.value,
                "message": f"Intent '{intent_name}' not found",
                "suggestion": "Use GET /api/v1/nbi/intents to see available intents"
            }
        )
    
    return {
        "success": True,
        "code": ErrorCode.SUCCESS.value,
        "message": "Intent found",
        "data": {
            "name": intent.name,
            "category": intent.category.value,
            "description": intent.description,
            "required_params": intent.required_params,
            "optional_params": intent.optional_params,
            "is_read_only": intent.is_read_only,
        }
    }


# ===== Device Endpoints (Database-backed) =====

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
                "default_strategy": d.default_strategy,
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
    if not device_id or len(device_id) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.INVALID_DEVICE_ID.value,
                "message": "device_id is required"
            }
        )
    
    try:
        device = await device_service.get(device_id)
        return DeviceDetailResponse(
            success=True,
            code=ErrorCode.SUCCESS.value,
            message="Device found",
            device={
                "device_id": device.device_id,
                "node_id": device.node_id,
                "vendor": device.vendor,
                "model": device.model,
                "role": device.role,
                "default_strategy": device.default_strategy,
                "oc_supported_intents": device.oc_supported_intents,
                "source": "database"
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
    
    Shows which intents are supported via OpenConfig
    
    **Error Codes:**
    - `DEVICE_NOT_FOUND`: ไม่พบ device
    """
    try:
        device = await device_service.get(device_id)
        
        # Group intents by support status
        oc_supported = []
        vendor_only = []
        
        for intent_name, oc_ok in device.oc_supported_intents.items():
            if oc_ok:
                oc_supported.append(intent_name)
            else:
                vendor_only.append(intent_name)
        
        return {
            "success": True,
            "code": ErrorCode.SUCCESS.value,
            "message": "Capabilities retrieved",
            "data": {
                "device_id": device_id,
                "node_id": device.node_id,
                "vendor": device.vendor,
                "default_strategy": device.default_strategy,
                "openconfig_supported": oc_supported,
                "vendor_only": vendor_only,
                "total_intents": len(oc_supported) + len(vendor_only)
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


# ===== ODL Sync Endpoints =====

@router.get("/odl/nodes")
async def get_odl_mounted_nodes():
    """
    ดึงรายการ nodes ที่ mount อยู่ใน ODL โดยตรง (real-time)
    
    **Error Codes:**
    - `ODL_CONNECTION_FAILED`: ไม่สามารถเชื่อมต่อ ODL ได้
    - `ODL_TIMEOUT`: ODL timeout
    """
    try:
        nodes = await odl_sync_service.get_odl_mounted_nodes()
        return {
            "success": True,
            "code": ErrorCode.SUCCESS.value,
            "message": f"Found {len(nodes)} nodes in ODL",
            "nodes": [
                {
                    "node_id": n["node_id"],
                    "connection_status": n["connection_status"],
                    "host": n.get("host"),
                    "port": n.get("port"),
                }
                for n in nodes
            ],
            "total": len(nodes),
            "source": "odl"
        }
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": ErrorCode.ODL_TIMEOUT.value,
                "message": "ODL connection timeout",
                "suggestion": "Check ODL server status and network connectivity"
            }
        )
    except Exception as e:
        logger.error(f"Failed to get ODL nodes: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_CONNECTION_FAILED.value,
                "message": f"Failed to connect to ODL: {str(e)}",
                "suggestion": "Check ODL server status and configuration"
            }
        )


@router.post("/sync", response_model=SyncResponse)
async def sync_devices_from_odl():
    """
    Sync ข้อมูล Device จาก ODL มา update ใน Database
    
    **Error Codes:**
    - `ODL_CONNECTION_FAILED`: ไม่สามารถเชื่อมต่อ ODL ได้
    - `DATABASE_ERROR`: Database update failed
    """
    try:
        result = await odl_sync_service.sync_devices_from_odl()
        
        has_errors = len(result.get("errors", [])) > 0
        synced_count = len(result.get("synced", []))
        not_found_count = len(result.get("not_found", []))
        
        return SyncResponse(
            success=not has_errors,
            code=ErrorCode.SUCCESS.value if not has_errors else ErrorCode.DATABASE_ERROR.value,
            message=f"Synced {synced_count} devices. {not_found_count} ODL nodes not in database.",
            data={
                "synced": result.get("synced", []),
                "not_found": result.get("not_found", []),
                "errors": result.get("errors", []),
                "timestamp": result.get("timestamp")
            }
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": ErrorCode.ODL_TIMEOUT.value,
                "message": "Sync timeout - ODL not responding"
            }
        )
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_CONNECTION_FAILED.value,
                "message": f"Sync failed: {str(e)}"
            }
        )


@router.post("/auto-create", response_model=SyncResponse)
async def auto_create_device_from_odl(request: AutoCreateRequest):
    """
    สร้าง DeviceNetwork อัตโนมัติจาก ODL node ที่ mount อยู่
    
    **Error Codes:**
    - `NODE_NOT_FOUND_IN_ODL`: Node ไม่พบใน ODL
    - `DEVICE_ALREADY_EXISTS`: Device with this node_id already exists
    - `INVALID_VENDOR`: Vendor ไม่ถูกต้อง
    """
    try:
        result = await odl_sync_service.auto_create_from_odl(
            node_id=request.node_id,
            vendor=request.vendor
        )
        
        return SyncResponse(
            success=True,
            code=ErrorCode.SUCCESS.value,
            message=f"Device created successfully from ODL node: {request.node_id}",
            data=result
        )
    except ValueError as e:
        error_msg = str(e)
        
        if "already exists" in error_msg.lower():
            code = ErrorCode.DEVICE_ALREADY_EXISTS
            status_code = status.HTTP_409_CONFLICT
        elif "not found" in error_msg.lower():
            code = ErrorCode.NODE_NOT_FOUND_IN_ODL
            status_code = status.HTTP_404_NOT_FOUND
        else:
            code = ErrorCode.INVALID_PARAMS
            status_code = status.HTTP_400_BAD_REQUEST
        
        raise HTTPException(status_code=status_code, detail={
            "code": code.value,
            "message": error_msg
        })
    except Exception as e:
        logger.error(f"Auto-create failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_CONNECTION_FAILED.value,
                "message": f"Failed to create device: {str(e)}"
            }
        )


# ===== Update NETCONF Credentials =====

@router.put("/devices/{node_id}/netconf")
async def update_netconf_credentials(node_id: str, request: UpdateNetconfRequest):
    """
    🔧 Update NETCONF credentials สำหรับ device
    
    ใช้ก่อน mount เพื่อกำหนด NETCONF connection info
    
    **Required fields for mount:**
    - `netconf_host`: IP/Hostname ของ device
    - `netconf_username`: Username สำหรับ NETCONF
    - `netconf_password`: Password สำหรับ NETCONF
    """
    from app.database import get_prisma_client
    
    prisma = get_prisma_client()
    
    try:
        # Find device
        device = await prisma.devicenetwork.find_first(
            where={"node_id": node_id}
        )
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": ErrorCode.DEVICE_NOT_FOUND.value,
                    "message": f"Device with node_id '{node_id}' not found"
                }
            )
        
        # Build update data
        update_data = {}
        if request.netconf_host is not None:
            update_data["netconf_host"] = request.netconf_host
        if request.netconf_port is not None:
            update_data["netconf_port"] = request.netconf_port
        if request.netconf_username is not None:
            update_data["netconf_username"] = request.netconf_username
        if request.netconf_password is not None:
            update_data["netconf_password"] = request.netconf_password
        if request.vendor is not None:
            update_data["vendor"] = request.vendor.upper()
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": ErrorCode.INVALID_PARAMS.value,
                    "message": "No fields to update"
                }
            )
        
        # Update device
        updated = await prisma.devicenetwork.update(
            where={"id": device.id},
            data=update_data
        )
        
        return {
            "success": True,
            "code": ErrorCode.SUCCESS.value,
            "message": f"NETCONF credentials updated for {node_id}",
            "data": {
                "node_id": updated.node_id,
                "netconf_host": updated.netconf_host,
                "netconf_port": updated.netconf_port,
                "netconf_username": updated.netconf_username,
                "vendor": updated.vendor,
                "ready_to_mount": bool(
                    updated.netconf_host and 
                    updated.netconf_username and 
                    updated.netconf_password
                )
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update NETCONF credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ErrorCode.DATABASE_ERROR.value,
                "message": f"Failed to update: {str(e)}"
            }
        )


# ===== Mount/Unmount Endpoints =====

@router.post("/devices/{node_id}/mount", response_model=MountResponse)
async def mount_device(node_id: str, request: MountRequest = MountRequest()):
    """
    🔌 Mount device ใน ODL
    
    ใช้ข้อมูล NETCONF credentials จาก Database เพื่อ mount ใน ODL
    
    **Error Codes:**
    - `DEVICE_NOT_FOUND`: ไม่พบ device ใน Database
    - `MISSING_NODE_ID`: Device ไม่มี node_id
    - `MISSING_NETCONF_HOST`: Device ไม่มี netconf_host หรือ ip_address
    - `MISSING_NETCONF_CREDENTIALS`: ไม่มี username/password
    - `DEVICE_ALREADY_MOUNTED`: Device mount อยู่แล้ว
    - `ODL_MOUNT_FAILED`: Mount failed
    - `MOUNT_TIMEOUT`: รอ connection timeout
    """
    try:
        if request.wait_for_connection:
            result = await odl_mount_service.mount_and_wait(
                node_id=node_id,
                max_wait_seconds=request.max_wait_seconds
            )
        else:
            result = await odl_mount_service.mount_device(node_id)
        
        # Determine response code
        if result.get("success"):
            code = ErrorCode.SUCCESS
        elif result.get("already_mounted"):
            code = ErrorCode.DEVICE_ALREADY_MOUNTED
        else:
            code = ErrorCode.ODL_MOUNT_FAILED
        
        return MountResponse(
            success=result.get("success", False),
            code=code.value,
            message=result.get("message", ""),
            node_id=result.get("node_id"),
            connection_status=result.get("connection_status"),
            device_status=result.get("device_status"),
            ready_for_intent=result.get("ready_for_intent", False),
            data={
                "wait_time_seconds": result.get("wait_time_seconds"),
                "node_id": node_id
            }
        )
        
    except ValueError as e:
        error_msg = str(e)
        
        # Determine specific error code
        if "not found" in error_msg.lower():
            code = ErrorCode.DEVICE_NOT_FOUND
            status_code = status.HTTP_404_NOT_FOUND
        elif "node_id" in error_msg.lower():
            code = ErrorCode.MISSING_NODE_ID
            status_code = status.HTTP_400_BAD_REQUEST
        elif "netconf_host" in error_msg.lower() or "ip_address" in error_msg.lower():
            code = ErrorCode.MISSING_NETCONF_HOST
            status_code = status.HTTP_400_BAD_REQUEST
        elif "username" in error_msg.lower() or "password" in error_msg.lower():
            code = ErrorCode.MISSING_NETCONF_CREDENTIALS
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            code = ErrorCode.INVALID_PARAMS
            status_code = status.HTTP_400_BAD_REQUEST
        
        raise HTTPException(status_code=status_code, detail={
            "code": code.value,
            "message": error_msg,
            "required_fields": ["node_id", "netconf_host or ip_address", "netconf_username", "netconf_password"]
        })
        
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": ErrorCode.MOUNT_TIMEOUT.value,
                "message": f"Mount timeout after {request.max_wait_seconds} seconds",
                "suggestion": "Check device reachability and NETCONF configuration"
            }
        )
        
    except Exception as e:
        logger.error(f"Mount failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_MOUNT_FAILED.value,
                "message": f"Mount failed: {str(e)}",
                "suggestion": "Check ODL logs and device connectivity"
            }
        )


@router.post("/devices/{node_id}/unmount", response_model=MountResponse)
async def unmount_device(node_id: str):
    """
    🔌 Unmount device จาก ODL
    
    **Error Codes:**
    - `DEVICE_NOT_FOUND`: ไม่พบ device
    - `DEVICE_NOT_MOUNTED`: Device ไม่ได้ mount อยู่
    - `ODL_UNMOUNT_FAILED`: Unmount failed
    """
    try:
        result = await odl_mount_service.unmount_device(node_id)
        
        return MountResponse(
            success=result.get("success", False),
            code=ErrorCode.SUCCESS.value if result.get("success") else ErrorCode.ODL_UNMOUNT_FAILED.value,
            message=result.get("message", ""),
            node_id=result.get("node_id"),
            connection_status="UNABLE_TO_CONNECT",
            device_status="OFFLINE",
            ready_for_intent=False,
            data={"node_id": node_id}
        )
        
    except ValueError as e:
        error_msg = str(e)
        
        if "not found" in error_msg.lower():
            code = ErrorCode.DEVICE_NOT_FOUND
            status_code = status.HTTP_404_NOT_FOUND
        elif "node_id" in error_msg.lower():
            code = ErrorCode.MISSING_NODE_ID
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            code = ErrorCode.DEVICE_NOT_MOUNTED
            status_code = status.HTTP_400_BAD_REQUEST
        
        raise HTTPException(status_code=status_code, detail={
            "code": code.value,
            "message": error_msg
        })
        
    except Exception as e:
        logger.error(f"Unmount failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_UNMOUNT_FAILED.value,
                "message": f"Unmount failed: {str(e)}"
            }
        )


@router.get("/devices/{node_id}/status", response_model=MountResponse)
async def check_device_status(node_id: str):
    """
    📊 Check connection status และ sync กับ Database
    
    **Error Codes:**
    - `DEVICE_NOT_FOUND`: ไม่พบ device
    - `DEVICE_NOT_CONNECTED`: Device ยัง connecting หรือ unable to connect
    - `ODL_CONNECTION_FAILED`: ไม่สามารถตรวจสอบ status ได้
    """
    try:
        result = await odl_mount_service.check_and_sync_status(node_id)
        
        # Determine code based on status
        connection_status = result.get("connection_status", "unknown")
        if result.get("ready_for_intent"):
            code = ErrorCode.SUCCESS
        elif connection_status == "connecting":
            code = ErrorCode.DEVICE_CONNECTING
        else:
            code = ErrorCode.DEVICE_NOT_CONNECTED
        
        return MountResponse(
            success=result.get("synced", False),
            code=code.value,
            message=result.get("message", ""),
            node_id=result.get("node_id"),
            connection_status=connection_status,
            device_status=result.get("device_status"),
            ready_for_intent=result.get("ready_for_intent", False),
            data={
                "node_id": node_id,
                "device_name": result.get("device_name"),
                "mounted": result.get("mounted", False)
            }
        )
        
    except ValueError as e:
        error_msg = str(e)
        
        if "not found" in error_msg.lower():
            code = ErrorCode.DEVICE_NOT_FOUND
            status_code = status.HTTP_404_NOT_FOUND
        elif "node_id" in error_msg.lower():
            code = ErrorCode.MISSING_NODE_ID
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            code = ErrorCode.INVALID_PARAMS
            status_code = status.HTTP_400_BAD_REQUEST
        
        raise HTTPException(status_code=status_code, detail={
            "code": code.value,
            "message": error_msg
        })
        
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_CONNECTION_FAILED.value,
                "message": f"Status check failed: {str(e)}"
            }
        )


# ===== Health Check Endpoint =====

@router.get("/health")
async def nbi_health_check():
    """
    NBI Health Check - ตรวจสอบการเชื่อมต่อ ODL และ Database
    
    **Returns:**
    - `odl_status`: ODL connection status
    - `db_status`: Database connection status
    """
    health = {
        "service": "NBI",
        "status": "healthy",
        "odl_status": "unknown",
        "db_status": "unknown",
        "checks": {}
    }
    
    # Check ODL
    try:
        nodes = await odl_sync_service.get_odl_mounted_nodes()
        health["odl_status"] = "connected"
        health["checks"]["odl"] = {
            "status": "ok",
            "mounted_nodes": len(nodes)
        }
    except Exception as e:
        health["odl_status"] = "disconnected"
        health["checks"]["odl"] = {
            "status": "error",
            "message": str(e)
        }
        health["status"] = "degraded"
    
    # Check Database
    try:
        devices = await device_service.list_all()
        health["db_status"] = "connected"
        health["checks"]["database"] = {
            "status": "ok",
            "total_devices": len(devices)
        }
    except Exception as e:
        health["db_status"] = "disconnected"
        health["checks"]["database"] = {
            "status": "error",
            "message": str(e)
        }
        health["status"] = "unhealthy"
    
    status_code = status.HTTP_200_OK if health["status"] == "healthy" else status.HTTP_503_SERVICE_UNAVAILABLE
    
    return JSONResponse(status_code=status_code, content={
        "success": health["status"] == "healthy",
        "code": ErrorCode.SUCCESS.value if health["status"] == "healthy" else ErrorCode.ODL_NOT_AVAILABLE.value,
        "message": f"NBI service is {health['status']}",
        "data": health
    })


# ===== Admin/Migration Endpoints =====

@router.post("/admin/migrate-node-ids", response_model=SyncResponse)
async def migrate_node_ids():
    """
    🔧 Migration: Generate node_id for devices that don't have one
    
    สำหรับ devices เดิมที่ไม่มี node_id จะสร้างจาก device_name โดย:
    - ลบ space และ special characters
    - แปลงเป็น lowercase
    - ใช้ underscore แทน space
    
    **ควรรันครั้งเดียวหลัง update**
    """
    from app.database import get_prisma_client
    import re
    
    prisma = get_prisma_client()
    
    try:
        # ดึง devices ที่ไม่มี node_id
        devices = await prisma.devicenetwork.find_many(
            where={"node_id": None}
        )
        
        if not devices:
            return SyncResponse(
                success=True,
                code=ErrorCode.SUCCESS.value,
                message="No devices need migration - all devices have node_id",
                data={"migrated": 0, "devices": []}
            )
        
        migrated = []
        errors = []
        
        for device in devices:
            try:
                # Generate node_id from device_name
                # 1. ลบ special characters ยกเว้น -, _
                # 2. แทน space ด้วย _
                # 3. ลบ leading/trailing _ หรือ -
                name = device.device_name
                node_id = re.sub(r'[^a-zA-Z0-9\s_-]', '', name)  # remove special chars
                node_id = re.sub(r'\s+', '_', node_id)           # space -> underscore
                node_id = re.sub(r'^[_-]+|[_-]+$', '', node_id)  # trim _ and - 
                node_id = node_id[:63]                            # max 63 chars
                
                # ถ้า node_id ว่าง ใช้ serial_number
                if not node_id:
                    node_id = re.sub(r'[^a-zA-Z0-9_-]', '', device.serial_number)[:63]
                
                # Check if node_id already exists
                existing = await prisma.devicenetwork.find_first(
                    where={"node_id": node_id}
                )
                
                if existing:
                    # เพิ่ม suffix ถ้าซ้ำ
                    node_id = f"{node_id}_{device.id[:8]}"
                
                # Update device
                await prisma.devicenetwork.update(
                    where={"id": device.id},
                    data={"node_id": node_id}
                )
                
                migrated.append({
                    "id": device.id,
                    "device_name": device.device_name,
                    "new_node_id": node_id
                })
                
            except Exception as e:
                errors.append({
                    "id": device.id,
                    "device_name": device.device_name,
                    "error": str(e)
                })
        
        return SyncResponse(
            success=len(errors) == 0,
            code=ErrorCode.SUCCESS.value if not errors else ErrorCode.DATABASE_ERROR.value,
            message=f"Migrated {len(migrated)} devices, {len(errors)} errors",
            data={
                "migrated": len(migrated),
                "devices": migrated,
                "errors": errors
            }
        )
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ErrorCode.DATABASE_ERROR.value,
                "message": f"Migration failed: {str(e)}"
            }
        )


@router.get("/admin/devices-without-node-id")
async def list_devices_without_node_id():
    """
    📋 List devices ที่ยังไม่มี node_id
    """
    from app.database import get_prisma_client
    
    prisma = get_prisma_client()
    
    devices = await prisma.devicenetwork.find_many(
        where={"node_id": None}
    )
    
    return {
        "success": True,
        "code": ErrorCode.SUCCESS.value,
        "message": f"Found {len(devices)} devices without node_id",
        "devices": [
            {
                "id": d.id,
                "device_name": d.device_name,
                "serial_number": d.serial_number,
                "suggested_node_id": re.sub(r'[^a-zA-Z0-9_-]', '_', d.device_name)[:63]
            }
            for d in devices
        ]
    }

