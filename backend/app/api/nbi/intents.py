"""
NBI Intent Endpoints
Intent execution and discovery endpoints
"""
import asyncio
from fastapi import APIRouter, HTTPException, status
from app.schemas.intent import IntentRequest, IntentResponse
from app.services.intent_service import IntentService
from app.core.intent_registry import IntentRegistry
from app.core.logging import logger
from app.core.errors import DeviceNotMounted
from app.services.driver_factory import DriverFactory

from .models import ErrorCode, IntentListResponse

router = APIRouter()
intent_service = IntentService()


@router.post("/intents", response_model=IntentResponse)
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
        "node_id": "CSR1000vT",
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
                "suggestion": detail.get("suggestion", f"Use POST /api/v1/nbi/devices/{req.node_id}/mount to mount the device first")
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


@router.get("/intents")
async def list_supported_intents():
    """
    Get all supported intents grouped by OS

    **Always returns 200**
    """
    try:
        intents_by_os = DriverFactory.get_intents_by_os()
        total = sum(v.get("total", 0) for v in intents_by_os.values())

        return {
            "success": True,
            "code": ErrorCode.SUCCESS.value,
            "message": f"Found {total} intents across {len(intents_by_os)} OS types",
            "intents_by_os": intents_by_os,
        }
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
