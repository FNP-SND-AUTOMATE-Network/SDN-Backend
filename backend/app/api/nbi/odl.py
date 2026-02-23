"""
NBI ODL Sync Endpoints
ODL node listing and sync endpoints
"""
import asyncio
from fastapi import APIRouter, HTTPException, status
from app.services.odl_sync_service import OdlSyncService
from app.core.logging import logger

from .models import ErrorCode, SyncResponse, OdlConfigRequest, OdlConfigResponse
from app.services.settings_service import SettingsService

router = APIRouter()
odl_sync_service = OdlSyncService()


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

@router.get("/odl/config", response_model=OdlConfigResponse)
async def get_odl_config():
    """
    ดึงค่า Config ของ ODL จากระบบ (ดึงจาก Cache/DB)
    """
    try:
        config = await SettingsService.get_odl_config()
        return OdlConfigResponse(
            success=True,
            data=config
        )
    except Exception as e:
        logger.error(f"Failed to get ODL config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.put("/odl/config", response_model=OdlConfigResponse)
async def update_odl_config(req: OdlConfigRequest):
    """
    บันทึกค่า ODL Config ใหม่ลง Database และอัปเดต Cache
    """
    try:
        config = await SettingsService.update_odl_config(
            base_url=req.odl_base_url,
            username=req.odl_username,
            password=req.odl_password,
            timeout=req.odl_timeout_sec,
            retry=req.odl_retry
        )
        return OdlConfigResponse(
            success=True,
            message="ODL config updated successfully",
            data=config
        )
    except Exception as e:
        logger.error(f"Failed to update ODL config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
