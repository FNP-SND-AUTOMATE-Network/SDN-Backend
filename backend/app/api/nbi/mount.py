"""
NBI Mount/Unmount Endpoints
Device mount, unmount, and status endpoints
"""
import asyncio
from fastapi import APIRouter, HTTPException, status, Depends, Query
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
        
        # Determine response based on result
        is_success = result.get("success", False)
        already_mounted = result.get("already_mounted", False)
        
        if is_success:
            # ✅ Device mounted AND connected → 200 OK
            return MountResponse(
                success=True,
                code=ErrorCode.SUCCESS.value,
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
        elif already_mounted:
            # Device already mounted and connected → 200 OK (idempotent)
            return MountResponse(
                success=True,
                code=ErrorCode.DEVICE_ALREADY_MOUNTED.value,
                message=result.get("message", ""),
                node_id=result.get("node_id"),
                connection_status=result.get("connection_status"),
                device_status=result.get("device_status"),
                ready_for_intent=True,
                data={"node_id": node_id}
            )
        else:
            # ❌ Mount sent but NOT connected → non-200
            connection_status = result.get("connection_status", "unknown")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": ErrorCode.ODL_MOUNT_FAILED.value,
                    "message": result.get("message", f"Mount failed: device status is '{connection_status}'"),
                    "node_id": node_id,
                    "connection_status": connection_status,
                    "device_status": result.get("device_status"),
                    "suggestion": (
                        "Device may still be connecting. "
                        "Use GET /api/v1/nbi/devices/{node_id}/status to check, "
                        "or retry with wait_for_connection=true"
                    )
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
        elif "profile" in error_msg.lower():
            code = ErrorCode.MISSING_USER_CREDENTIALS
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            code = ErrorCode.INVALID_PARAMS
            status_code = status.HTTP_400_BAD_REQUEST
        
        detail_data = {
            "code": code.value,
            "message": error_msg
        }
        
        if code == ErrorCode.INVALID_PARAMS:
            detail_data["required_fields"] = ["node_id", "netconf_host or ip_address", "netconf_username", "netconf_password"]
            
        raise HTTPException(status_code=status_code, detail=detail_data)
        
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


@router.delete("/devices/{node_id}/mount", response_model=MountResponse)
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

@router.get("/devices/{node_id}/wait-ready")
async def wait_for_device_ready(
    node_id: str,
    max_wait_seconds: int = Query(
        120,
        ge=5,
        le=300,
        description="Maximum seconds to wait for ODL to finish mounting (default 120s). "
                    "Cisco ASR hardware typically needs 30–90 s to download YANG modules."
    ),
    check_interval: int = Query(
        5,
        ge=2,
        le=30,
        description="Polling interval in seconds (default 5s)"
    ),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    ⏳ Poll ODL until the device becomes **fully connected** (or timeout).

    Use this endpoint **immediately after** `POST /devices/{node_id}/mount` to
    wait for ODL to finish downloading and compiling all YANG modules before
    issuing any data-plane requests (get-interfaces, push-config, etc.).

    ### Why this matters
    ODL reports HTTP 201 / 200 as soon as the mount entry is written to the
    *configuration* datastore.  The actual NETCONF session establishment and
    YANG schema compilation happen **asynchronously** in the background and can
    take 30–120 seconds on real Cisco ASR hardware.  Sending NETCONF RPCs
    (e.g. `get-config`) while `connection_status == 'connecting'` floods the
    internal RPC queue, which causes ODL to tear down the session permanently
    and leaves the node in a stuck state that survives unmount/remount.

    ### Flow
    ```
    POST /mount  → 200 OK (mount entry created)
          ↓
    GET  /wait-ready  → polls every {check_interval}s
          ↓  (when connected)
    GET  /interfaces/sync     → safe to call
    ```

    ### Response codes
    | `ready` | `connection_status`    | Meaning                              |
    |---------|------------------------|--------------------------------------|
    | `true`  | `connected`            | Safe to call interface / config APIs |
    | `false` | `connecting`           | Timed out — keep polling             |
    | `false` | `unable-to-connect`    | Auth / reachability failure          |
    """
    try:
        result = await odl_mount_service.wait_until_connected(
            node_id=node_id,
            max_wait_seconds=max_wait_seconds,
            check_interval=check_interval,
        )

        conn = result.get("connection_status", "unknown")

        if result.get("ready"):
            code = ErrorCode.SUCCESS
        elif conn == "connecting":
            code = ErrorCode.DEVICE_CONNECTING
        else:
            code = ErrorCode.DEVICE_NOT_CONNECTED

        return MountResponse(
            success=result["ready"],
            code=code.value,
            message=result["message"],
            node_id=node_id,
            connection_status=conn,
            device_status="ONLINE" if result["ready"] else "OFFLINE",
            ready_for_intent=result["ready"],
            data={
                "node_id": node_id,
                "waited_seconds": result.get("waited_seconds", 0),
                "max_wait_seconds": max_wait_seconds,
            },
        )

    except ValueError as e:
        error_msg = str(e)
        status_code = (
            status.HTTP_404_NOT_FOUND if "not found" in error_msg.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail={
            "code": ErrorCode.DEVICE_NOT_FOUND.value if "not found" in error_msg.lower()
                    else ErrorCode.INVALID_PARAMS.value,
            "message": error_msg,
        })
    except Exception as e:
        logger.error(f"wait-ready failed for {node_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": ErrorCode.ODL_CONNECTION_FAILED.value, "message": str(e)},
        )


@router.post("/devices/{node_id}/force-remount", response_model=MountResponse)
async def force_remount_device(
    node_id: str,
    request: MountRequest = MountRequest(),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    🔄 Force-remount a stuck device in ODL.

    Use this when a device node is **stuck** in ODL (e.g. it survived `unmount`
    and cannot be mounted again).  This endpoint:

    1. `DELETE` the node from ODL **config** datastore (handles 404 gracefully)
    2. Waits 10 seconds for ODL to fully tear down the NETCONF session
    3. Verifies the node is gone from **operational** datastore
    4. Re-mounts the device using credentials from the database
    5. Polls until `connected` (respects `max_wait_seconds`)

    ### When to use
    - Keepalive RPCs are flooding the log with "session is disconnected"
    - `GET /status` returns `connection_status: none` or `unable-to-connect`
      even though you already called `unmount` + `mount`
    - The node is visible in ODL operational DS but not in config DS

    ### Concurrency safety
    Uses per-device locking — concurrent force-remount calls on the same
    device will be serialized automatically.
    """
    try:
        user_id = current_user["id"]

        result = await odl_mount_service.force_remount(
            node_id=node_id,
            user_id=user_id,
            max_wait_seconds=request.max_wait_seconds,
        )

        code = ErrorCode.SUCCESS if result.get("success") else ErrorCode.ODL_MOUNT_FAILED

        return MountResponse(
            success=result.get("success", False),
            code=code.value,
            message=result.get("message", ""),
            node_id=result.get("node_id"),
            connection_status=result.get("connection_status"),
            device_status=result.get("device_status"),
            ready_for_intent=result.get("ready_for_intent", False),
            data={
                "node_id": node_id,
                "wait_time_seconds": result.get("wait_time_seconds"),
                "force_remount": True,
            },
        )

    except ValueError as e:
        error_msg = str(e)
        status_code = (
            status.HTTP_404_NOT_FOUND if "not found" in error_msg.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail={
            "code": ErrorCode.DEVICE_NOT_FOUND.value if "not found" in error_msg.lower()
                    else ErrorCode.INVALID_PARAMS.value,
            "message": error_msg,
        })
    except Exception as e:
        logger.error(f"[force-remount] Failed for {node_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_MOUNT_FAILED.value,
                "message": f"Force-remount failed: {str(e)}",
                "suggestion": "Check ODL logs for NETCONF session errors",
            },
        )

