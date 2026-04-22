"""
NBI Intent Endpoints
Intent execution and discovery endpoints
"""
import asyncio
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, status, Depends
from app.schemas.intent import IntentRequest, IntentResponse, IntentBulkRequest, IntentBulkResponse
from app.services.intent_service import IntentService
from app.core.intent_registry import IntentRegistry
from app.core.logging import logger
from app.core.errors import DeviceNotMounted
from app.services.driver_factory import DriverFactory
from app.api.users import get_current_user, check_engineer_permission

from .models import ErrorCode, IntentListResponse

router = APIRouter()
intent_service = IntentService()


@router.post("/intents", response_model=IntentResponse)
async def handle_intent(
    req: IntentRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Execute a network intent (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
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
        return await intent_service.handle(req)
    except DeviceNotMounted as e:
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
        if "not found" in error_msg.lower():
            code, status_code = ErrorCode.DEVICE_NOT_FOUND, status.HTTP_404_NOT_FOUND
        elif "not connected" in error_msg.lower() or "mount point" in error_msg.lower():
            code, status_code = ErrorCode.DEVICE_NOT_CONNECTED, status.HTTP_400_BAD_REQUEST
        else:
            code, status_code = ErrorCode.INVALID_PARAMS, status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail={"code": code.value, "message": error_msg})
    except asyncio.TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail={
            "code": ErrorCode.ODL_TIMEOUT.value, "message": "ODL request timeout"
        })
    except Exception as e:
        logger.error(f"Intent execution failed: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={
            "code": ErrorCode.ODL_REQUEST_FAILED.value,
            "message": f"Intent execution failed: {str(e)}"
        })


@router.get("/intents")
async def list_supported_intents(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """List all supported intents (requires login)"""
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={
            "code": ErrorCode.DATABASE_ERROR.value,
            "message": "Failed to get intent list"
        })


@router.get("/intents/{intent_name}")
async def get_intent_info(
    intent_name: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Get details for a specific intent (requires login)"""
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

    intents_by_os = DriverFactory.get_intents_by_os()
    vendors_response = {}
    for os_str, os_data in intents_by_os.items():
        if intent_name in os_data.get("intents", []):
            vendor_prefix = os_str.split("_")[0].lower()
            if vendor_prefix in intent.vendor_params:
                vendors_response[vendor_prefix] = intent.vendor_params[vendor_prefix]
            elif vendor_prefix not in vendors_response:
                vendors_response[vendor_prefix] = {
                    "required_params": intent.required_params,
                    "optional_params": intent.optional_params
                }

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
            "vendors": vendors_response,
            "is_read_only": intent.is_read_only,
        }
    }


@router.post(
    "/intents/bulk",
    response_model=IntentBulkResponse,
    summary="Bulk execute intents (Fail-Fast)",
    description=(
        "Execute multiple intents sequentially on one or more devices.\n\n"
        "**Fail-Fast Behavior:** If any intent fails, all subsequent intents "
        "in the queue are immediately cancelled and marked as `CANCELLED`.\n\n"
        "Returns `200` if all intents succeed, `207 Multi-Status` if there are partial failures."
    ),
)
async def handle_bulk_intent(
    req: IntentBulkRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Bulk execute intents (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await intent_service.handle_bulk(req)
        if not result.success:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=207, content=result.model_dump())
        return result
    except Exception as e:
        logger.error(f"Bulk intent execution failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={
            "code": ErrorCode.ODL_REQUEST_FAILED.value,
            "message": f"Bulk intent execution failed: {str(e)}"
        })
