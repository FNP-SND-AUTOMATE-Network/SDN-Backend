"""
NBI (Northbound Interface) API
Intent-Based API สำหรับ Network Operations

Flow:
1. สร้าง Device ใน DB (พร้อม node_id และ NETCONF credentials)
2. Mount Device ใน ODL ผ่าน API
3. Check/Sync Connection Status
4. ใช้งาน Intent API
"""
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app.schemas.intent import IntentRequest, IntentResponse
from app.services.intent_service import IntentService
from app.services.device_profile_service_db import DeviceProfileService
from app.services.odl_sync_service import OdlSyncService
from app.services.odl_mount_service import OdlMountService
from app.core.intent_registry import IntentRegistry

router = APIRouter(prefix="/api/v1/nbi", tags=["NBI"])
intent_service = IntentService()
device_service = DeviceProfileService()
odl_sync_service = OdlSyncService()
odl_mount_service = OdlMountService()


# ===== Request/Response Models =====

class MountRequest(BaseModel):
    """Request body สำหรับ mount device"""
    wait_for_connection: bool = Field(
        default=True, 
        description="รอจนกว่าจะ connected (max 30s)"
    )
    max_wait_seconds: int = Field(
        default=30,
        description="เวลารอสูงสุด (วินาที)"
    )


class MountResponse(BaseModel):
    """Response สำหรับ mount operations"""
    success: bool
    message: str
    node_id: Optional[str] = None
    connection_status: Optional[str] = None
    device_status: Optional[str] = None
    ready_for_intent: bool = False
    data: Optional[Dict[str, Any]] = None


class SyncResponse(BaseModel):
    """Response สำหรับ sync operations"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class AutoCreateRequest(BaseModel):
    """Request body สำหรับ auto-create device จาก ODL"""
    node_id: str
    vendor: str = "cisco"


# ===== Intent Endpoints =====

@router.post("/intent", response_model=IntentResponse)
async def handle_intent(req: IntentRequest):
    """
    Execute an Intent-based network operation
    
    Intent format: `category.action` (e.g., `interface.set_ipv4`, `show.interface`)
    
    Example Request:
    ```json
    {
        "intent": "show.interface",
        "deviceId": "CSR1",
        "params": {
            "interface": "GigabitEthernet1"
        }
    }
    ```
    
    Note: deviceId can be:
    - node_id (ODL node name, e.g., "CSR1")
    - device_name (จาก DeviceNetwork)
    - database UUID
    """
    return await intent_service.handle(req)


# ===== Discovery Endpoints =====

@router.get("/intents", response_model=Dict[str, List[str]])
async def list_supported_intents():
    """
    Get all supported intents grouped by category
    
    Returns:
    ```json
    {
        "interface": ["interface.set_ipv4", "interface.enable", ...],
        "show": ["show.interface", "show.interfaces", ...],
        "routing": ["routing.static.add", ...],
        "system": ["system.set_hostname", ...]
    }
    ```
    """
    return IntentRegistry.get_supported_intents()


@router.get("/intents/{intent_name}")
async def get_intent_info(intent_name: str):
    """
    Get detailed information about a specific intent
    
    Returns required params, description, etc.
    """
    intent = IntentRegistry.get(intent_name)
    if not intent:
        return {"error": f"Intent not found: {intent_name}"}
    
    return {
        "name": intent.name,
        "category": intent.category.value,
        "description": intent.description,
        "required_params": intent.required_params,
        "optional_params": intent.optional_params,
        "is_read_only": intent.is_read_only,
    }


# ===== Device Endpoints (Database-backed) =====

@router.get("/devices")
async def list_devices(
    mounted_only: bool = Query(False, description="แสดงเฉพาะ devices ที่ mount ใน ODL"),
    vendor: Optional[str] = Query(None, description="Filter by vendor (cisco, huawei, etc.)"),
):
    """
    Get all registered devices from Database
    
    Devices มาจากตาราง DeviceNetwork ใน Database
    สามารถ sync จาก ODL ได้ผ่าน POST /sync
    
    Query Parameters:
    - mounted_only: แสดงเฉพาะ devices ที่ mount ใน ODL
    - vendor: Filter by vendor
    """
    if mounted_only:
        devices = await device_service.list_mounted()
    elif vendor:
        devices = await device_service.list_by_vendor(vendor)
    else:
        devices = await device_service.list_all()
    
    return {
        "devices": [
            {
                "device_id": d.device_id,
                "node_id": d.node_id,
                "vendor": d.vendor,
                "model": d.model,
                "role": d.role,
                "default_strategy": d.default_strategy,
            }
            for d in devices
        ],
        "total": len(devices),
        "source": "database"
    }


@router.get("/devices/{device_id}")
async def get_device_info(device_id: str):
    """
    Get detailed information about a specific device
    
    device_id สามารถเป็น:
    - node_id (ODL node name)
    - device_name
    - database UUID
    """
    try:
        device = await device_service.get(device_id)
        return {
            "device_id": device.device_id,
            "node_id": device.node_id,
            "vendor": device.vendor,
            "model": device.model,
            "role": device.role,
            "default_strategy": device.default_strategy,
            "oc_supported_intents": device.oc_supported_intents,
            "source": "database"
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices/{device_id}/capabilities")
async def get_device_capabilities(device_id: str):
    """
    Get intent capabilities for a specific device
    
    Shows which intents are supported via OpenConfig
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
            "device_id": device_id,
            "node_id": device.node_id,
            "vendor": device.vendor,
            "default_strategy": device.default_strategy,
            "openconfig_supported": oc_supported,
            "vendor_only": vendor_only,
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# ===== ODL Sync Endpoints =====

@router.get("/odl/nodes")
async def get_odl_mounted_nodes():
    """
    ดึงรายการ nodes ที่ mount อยู่ใน ODL โดยตรง (real-time)
    
    ไม่ผ่าน Database - ดึงจาก ODL RESTCONF API โดยตรง
    """
    try:
        nodes = await odl_sync_service.get_odl_mounted_nodes()
        return {
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
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to ODL: {str(e)}")


@router.post("/sync", response_model=SyncResponse)
async def sync_devices_from_odl():
    """
    Sync ข้อมูล Device จาก ODL มา update ใน Database
    
    Flow:
    1. ดึง mounted nodes จาก ODL
    2. Update DeviceNetwork ที่มี node_id ตรงกัน
    3. Mark devices ที่ไม่มีใน ODL เป็น unmounted
    
    Note: 
    - ต้องสร้าง DeviceNetwork และกำหนด node_id ก่อน จึงจะ sync ได้
    - หรือใช้ POST /auto-create เพื่อสร้างจาก ODL โดยอัตโนมัติ
    """
    try:
        result = await odl_sync_service.sync_devices_from_odl()
        
        return SyncResponse(
            success=len(result["errors"]) == 0,
            message=f"Synced {len(result['synced'])} devices. {len(result['not_found'])} ODL nodes not in database.",
            data=result
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sync failed: {str(e)}")


@router.post("/auto-create", response_model=SyncResponse)
async def auto_create_device_from_odl(request: AutoCreateRequest):
    """
    สร้าง DeviceNetwork อัตโนมัติจาก ODL node ที่ mount อยู่
    
    ใช้เมื่อต้องการเพิ่ม device ใหม่จาก ODL โดยไม่ต้องกรอกข้อมูลเอง
    
    Request Body:
    - node_id: ODL node-id ที่ต้องการสร้าง
    - vendor: Vendor ของ device (default: cisco)
    
    Example:
    ```json
    {
        "node_id": "CSR1",
        "vendor": "cisco"
    }
    ```
    """
    try:
        result = await odl_sync_service.auto_create_from_odl(
            node_id=request.node_id,
            vendor=request.vendor
        )
        
        return SyncResponse(
            success=True,
            message=f"Device created successfully from ODL node: {request.node_id}",
            data=result
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to create device: {str(e)}")


# ===== Mount/Unmount Endpoints =====

@router.post("/devices/{device_id}/mount", response_model=MountResponse)
async def mount_device(device_id: str, request: MountRequest = MountRequest()):
    """
    🔌 Mount device ใน ODL
    
    ใช้ข้อมูล NETCONF credentials จาก Database เพื่อ mount ใน ODL
    
    **Prerequisites:**
    - Device ต้องมี node_id
    - Device ต้องมี netconf_host (หรือ ip_address)
    - Device ต้องมี netconf_username และ netconf_password
    
    **Options:**
    - wait_for_connection: รอจนกว่าจะ connected (default: true)
    - max_wait_seconds: เวลารอสูงสุด (default: 30)
    
    **Example:**
    ```json
    POST /api/v1/nbi/devices/{device_id}/mount
    {
        "wait_for_connection": true,
        "max_wait_seconds": 30
    }
    ```
    """
    try:
        if request.wait_for_connection:
            result = await odl_mount_service.mount_and_wait(
                device_id=device_id,
                max_wait_seconds=request.max_wait_seconds
            )
        else:
            result = await odl_mount_service.mount_device(device_id)
        
        return MountResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            node_id=result.get("node_id"),
            connection_status=result.get("connection_status"),
            device_status=result.get("device_status"),
            ready_for_intent=result.get("ready_for_intent", False),
            data=result
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Mount failed: {str(e)}")


@router.post("/devices/{device_id}/unmount", response_model=MountResponse)
async def unmount_device(device_id: str):
    """
    🔌 Unmount device จาก ODL
    
    ลบ node ออกจาก ODL topology-netconf
    Device จะยังคงอยู่ใน Database แต่ status จะเปลี่ยนเป็น OFFLINE
    """
    try:
        result = await odl_mount_service.unmount_device(device_id)
        
        return MountResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            node_id=result.get("node_id"),
            connection_status="not-mounted",
            device_status="OFFLINE",
            ready_for_intent=False
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Unmount failed: {str(e)}")


@router.get("/devices/{device_id}/status", response_model=MountResponse)
async def check_device_status(device_id: str):
    """
    📊 Check connection status และ sync กับ Database
    
    ดึง status จาก ODL และ update ใน Database
    ใช้เพื่อตรวจสอบว่า device พร้อมใช้งาน Intent หรือยัง
    """
    try:
        result = await odl_mount_service.check_and_sync_status(device_id)
        
        return MountResponse(
            success=result.get("synced", False),
            message=result.get("message", ""),
            node_id=result.get("node_id"),
            connection_status=result.get("connection_status"),
            device_status=result.get("device_status"),
            ready_for_intent=result.get("ready_for_intent", False),
            data=result
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Status check failed: {str(e)}")
