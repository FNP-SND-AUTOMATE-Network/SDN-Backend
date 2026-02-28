"""
NBI OpenFlow Flow Management Endpoints
สร้าง / ลบ / ดู OpenFlow Flow Rules ผ่าน ODL RESTCONF API

Endpoints:
  POST   /flows                       - เพิ่ม flow rule
  DELETE /flows/{flow_id}             - ลบ flow rule
  GET    /devices/{node_id}/flows     - ดู flow ทั้งหมดของ device
"""
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status
from app.services.openflow_service import OpenFlowService
from app.core.logging import logger
from app.core.errors import OdlRequestError

from .models import ErrorCode, FlowAddRequest, FlowDeleteRequest, FlowResponse

router = APIRouter()
openflow_service = OpenFlowService()


# ──────────────────────────────────────────────────────────────
# POST /flows  →  เพิ่ม Flow Rule
# ──────────────────────────────────────────────────────────────
@router.post("/flows", response_model=FlowResponse)
async def add_flow(request: FlowAddRequest):
    """
    🔀 เพิ่ม OpenFlow Flow Rule

    Frontend ส่ง node_id + interface UUIDs มา →
    Backend query DB หา port_number →
    สร้าง payload ส่ง PUT ไป ODL

    **Request Body:**
    - `flow_id`: ชื่อกฎ (เช่น "ovs1-p1-to-p2")
    - `node_id`: node_id ของ switch (เช่น "openflow:1")
    - `inbound_interface_id`: UUID ของ Interface ขาเข้า
    - `outbound_interface_id`: UUID ของ Interface ขาออก
    - `priority`: ความสำคัญของกฎ (default: 500)
    - `table_id`: Flow Table ID (default: 0)

    **Error Codes:**
    - `DEVICE_NOT_FOUND`: ไม่พบ device
    - `INVALID_PARAMS`: interface ไม่พบ / ไม่มี port_number
    - `ODL_REQUEST_FAILED`: ODL request failed
    """
    try:
        result = await openflow_service.add_flow(
            flow_id=request.flow_id,
            node_id=request.node_id,
            inbound_interface_id=request.inbound_interface_id,
            outbound_interface_id=request.outbound_interface_id,
            priority=request.priority,
            table_id=request.table_id,
        )

        return FlowResponse(
            success=True,
            code=ErrorCode.SUCCESS.value,
            message=result["message"],
            data=result,
        )

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            code = ErrorCode.DEVICE_NOT_FOUND
            status_code = status.HTTP_404_NOT_FOUND
        else:
            code = ErrorCode.INVALID_PARAMS
            status_code = status.HTTP_400_BAD_REQUEST

        raise HTTPException(
            status_code=status_code,
            detail={"code": code.value, "message": error_msg},
        )

    except OdlRequestError as e:
        logger.error(f"ODL request failed for flow.add: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_REQUEST_FAILED.value,
                "message": f"ODL request failed: {str(e)}",
                "details": getattr(e, "details", None),
            },
        )

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": ErrorCode.ODL_TIMEOUT.value,
                "message": "ODL request timeout while adding flow",
            },
        )

    except Exception as e:
        logger.error(f"Unexpected error in add_flow: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ErrorCode.ODL_REQUEST_FAILED.value,
                "message": f"Unexpected error: {str(e)}",
            },
        )


# ──────────────────────────────────────────────────────────────
# DELETE /flows/{flow_id}  →  ลบ Flow Rule
# ──────────────────────────────────────────────────────────────
@router.delete("/flows/{flow_id}", response_model=FlowResponse)
async def delete_flow(
    flow_id: str,
    node_id: str = Query(..., description="node_id ของ OpenFlow switch"),
    table_id: int = Query(default=0, ge=0, le=255, description="Flow Table ID"),
):
    """
    🗑️ ลบ OpenFlow Flow Rule

    **Path Params:**
    - `flow_id`: ชื่อกฎที่ต้องการลบ

    **Query Params:**
    - `node_id`: node_id ของ switch (required)
    - `table_id`: Flow Table ID (default: 0)

    **Error Codes:**
    - `DEVICE_NOT_FOUND`: ไม่พบ device
    - `ODL_REQUEST_FAILED`: ODL DELETE failed
    """
    try:
        result = await openflow_service.delete_flow(
            flow_id=flow_id,
            node_id=node_id,
            table_id=table_id,
        )

        return FlowResponse(
            success=True,
            code=ErrorCode.SUCCESS.value,
            message=result["message"],
            data=result,
        )

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            code = ErrorCode.DEVICE_NOT_FOUND
            status_code = status.HTTP_404_NOT_FOUND
        else:
            code = ErrorCode.INVALID_PARAMS
            status_code = status.HTTP_400_BAD_REQUEST

        raise HTTPException(
            status_code=status_code,
            detail={"code": code.value, "message": error_msg},
        )

    except OdlRequestError as e:
        logger.error(f"ODL request failed for flow.delete: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_REQUEST_FAILED.value,
                "message": f"ODL DELETE failed: {str(e)}",
                "details": getattr(e, "details", None),
            },
        )

    except Exception as e:
        logger.error(f"Unexpected error in delete_flow: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ErrorCode.ODL_REQUEST_FAILED.value,
                "message": f"Unexpected error: {str(e)}",
            },
        )


# ──────────────────────────────────────────────────────────────
# GET /devices/{node_id}/flows  →  ดู Flows ทั้งหมด
# ──────────────────────────────────────────────────────────────
@router.get("/devices/{node_id}/flows", response_model=FlowResponse)
async def get_flows(
    node_id: str,
    table_id: Optional[int] = Query(
        default=None, ge=0, le=255, description="Filter by table ID (optional)"
    ),
):
    """
    📋 ดู OpenFlow Flow Rules ทั้งหมดของ Device

    **Path Params:**
    - `node_id`: node_id ของ switch (เช่น "openflow:1")

    **Query Params:**
    - `table_id`: ถ้าระบุ จะดูเฉพาะ table นั้น (optional)

    **Error Codes:**
    - `DEVICE_NOT_FOUND`: ไม่พบ device
    - `ODL_REQUEST_FAILED`: ODL GET failed
    """
    try:
        result = await openflow_service.get_flows(
            node_id=node_id,
            table_id=table_id,
        )

        return FlowResponse(
            success=True,
            code=ErrorCode.SUCCESS.value,
            message=result["message"],
            data=result,
        )

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            code = ErrorCode.DEVICE_NOT_FOUND
            status_code = status.HTTP_404_NOT_FOUND
        else:
            code = ErrorCode.INVALID_PARAMS
            status_code = status.HTTP_400_BAD_REQUEST

        raise HTTPException(
            status_code=status_code,
            detail={"code": code.value, "message": error_msg},
        )

    except OdlRequestError as e:
        logger.error(f"ODL request failed for show.flows: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_REQUEST_FAILED.value,
                "message": f"ODL GET failed: {str(e)}",
                "details": getattr(e, "details", None),
            },
        )

    except Exception as e:
        logger.error(f"Unexpected error in get_flows: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ErrorCode.ODL_REQUEST_FAILED.value,
                "message": f"Unexpected error: {str(e)}",
            },
        )
