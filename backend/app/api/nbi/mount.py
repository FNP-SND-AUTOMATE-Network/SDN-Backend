"""
NBI Mount/Unmount Endpoints
Device mount, unmount, and status endpoints
"""
import asyncio
from fastapi import APIRouter, HTTPException, status, Depends
from typing import Dict, Any
from app.services.odl_mount_service import OdlMountService
from app.core.logging import logger
from app.api.users import get_current_user

from .models import ErrorCode, MountRequest, MountResponse

router = APIRouter()
odl_mount_service = OdlMountService()


@router.post("/devices/{node_id}/mount", response_model=MountResponse)
async def mount_device(
    node_id: str, 
    request: MountRequest = MountRequest(),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
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
        user_id = current_user["id"]
        
        if request.wait_for_connection:
            result = await odl_mount_service.mount_and_wait(
                node_id=node_id,
                user_id=user_id,
                max_wait_seconds=request.max_wait_seconds
            )
        else:
            result = await odl_mount_service.mount_device(node_id, user_id=user_id)
        
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
async def unmount_device(
    node_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
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
async def check_device_status(
    node_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
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
