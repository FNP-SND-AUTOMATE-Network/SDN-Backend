"""
NBI Health Check Endpoint
"""
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from app.services.device_profile_service_db import DeviceProfileService
from app.services.odl_sync_service import OdlSyncService

from .models import ErrorCode

router = APIRouter()
device_service = DeviceProfileService()
odl_sync_service = OdlSyncService()


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
