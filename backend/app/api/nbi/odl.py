"""
NBI ODL Sync Endpoints
ODL node listing and sync endpoints
"""
import asyncio
from fastapi import APIRouter, HTTPException, status
from app.services.odl_sync_service import OdlSyncService
from app.core.config import settings
from app.core.logging import logger

from .models import ErrorCode, SyncResponse, OdlConfigResponse

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


@router.post("/odl/sync", response_model=SyncResponse)
async def sync_netconf_devices_from_odl():
    """
    Sync ข้อมูล Device จาก ODL มา update ใน Database
    
    **Error Codes:**
    - `ODL_CONNECTION_FAILED`: ไม่สามารถเชื่อมต่อ ODL ได้
    - `DATABASE_ERROR`: Database update failed
    """
    try:
        result = await odl_sync_service.sync_netconf_devices_from_odl()
        
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
    ดึงค่า Config ของ ODL จากระบบ (อ่านจาก .env)
    """
    config = {
        "ODL_BASE_URL": settings.ODL_BASE_URL,
        "ODL_USERNAME": settings.ODL_USERNAME,
        "ODL_PASSWORD": "********",  # ซ่อน password
        "ODL_TIMEOUT_SEC": settings.ODL_TIMEOUT_SEC,
        "ODL_RETRY": settings.ODL_RETRY,
    }
    return OdlConfigResponse(
        success=True,
        message="ODL config loaded from .env",
        data=config,
    )


@router.post("/odl/sync-all", response_model=SyncResponse)
async def sync_all_devices():
    """
    Sync ข้อมูล Device จาก NETCONF topology ใน ODL

    **Response:**
    - `netconf`: ผลลัพธ์จากการ sync NETCONF devices
    - `summary`: สรุปรวม (total_synced, total_not_found, total_errors)
    """
    try:
        result = await odl_sync_service.sync_all_devices()

        total_errors = result["summary"]["total_errors"]
        total_synced = result["summary"]["total_synced"]
        total_not_found = result["summary"]["total_not_found"]

        return SyncResponse(
            success=total_errors == 0,
            code=ErrorCode.SUCCESS.value if total_errors == 0 else ErrorCode.DATABASE_ERROR.value,
            message=(
                f"Unified sync completed: {total_synced} devices synced, "
                f"{total_not_found} not found in DB."
            ),
            data=result,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": ErrorCode.ODL_TIMEOUT.value,
                "message": "Unified sync timeout - ODL not responding",
            },
        )
    except Exception as e:
        logger.error(f"Unified sync failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_CONNECTION_FAILED.value,
                "message": f"Unified sync failed: {str(e)}",
            },
        )


@router.post("/devices/{node_id}/sync-status")
async def sync_single_device_status(node_id: str):
    """
    Sync connection status ของ device ตัวเดียวจาก ODL → DB

    ดึง connection-status จาก NETCONF topology

    **Response:**
    - `previous_status`: สถานะก่อน sync
    - `current_status`: สถานะหลัง sync
    - `connection_status`: raw status จาก ODL (เช่น "connected", "not-mounted")
    - `protocol`: NETCONF

    **Error Codes:**
    - `404`: Device ไม่พบใน database
    - `502`: ODL ไม่ตอบ
    """
    try:
        result = await odl_sync_service.sync_single_device_status(node_id)
        return {
            "success": True,
            "message": f"Device '{node_id}' status synced: {result['previous_status']} → {result['current_status']}",
            "data": result,
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DEVICE_NOT_FOUND",
                "message": str(e),
            },
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": ErrorCode.ODL_TIMEOUT.value,
                "message": f"Sync status timeout for {node_id} - ODL not responding",
            },
        )
    except Exception as e:
        logger.error(f"Single device sync failed for {node_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_CONNECTION_FAILED.value,
                "message": f"Failed to sync status for {node_id}: {str(e)}",
            },
        )
