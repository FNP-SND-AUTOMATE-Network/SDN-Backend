"""
NBI OpenFlow Flow Management Endpoints
สร้าง / ลบ / ดู OpenFlow Flow Rules ผ่าน ODL RESTCONF API
"""
import asyncio
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, status, Depends
from app.services.openflow_service import OpenFlowService
from app.core.logging import logger
from app.core.errors import OdlRequestError
from app.api.users import get_current_user, check_engineer_permission, check_admin_permission
from app.utils.request_helpers import validate_path_param

from .models import (
    ErrorCode,
    FlowAddRequest,
    FlowResponse,
    TrafficSteerRequest,
    ArpFloodRequest,
    MacSteerRequest,
    IpSteerRequest,
    DefaultGatewayRequest,
    SubnetSteerRequest,
    AclMacDropRequest,
    AclIpBlacklistRequest,
    AclPortDropRequest,
    AclWhitelistRequest,
    IcmpControlRequest,
    FlowRuleItem,
    FlowRuleListResponse,
    FlowDeleteRequest,
    FlowTemplateResponse,
)

router = APIRouter()
openflow_service = OpenFlowService()


# ── Shared Error Handler ──────────────────────────────────────────────────────
def _handle_flow_error(e: Exception, operation: str):
    if isinstance(e, ValueError):
        error_msg = str(e)
        code = ErrorCode.DEVICE_NOT_FOUND if "not found" in error_msg.lower() else ErrorCode.INVALID_PARAMS
        status_code = status.HTTP_404_NOT_FOUND if "not found" in error_msg.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail={"code": code.value, "message": error_msg})
    if isinstance(e, OdlRequestError):
        logger.error(f"ODL request failed for {operation}: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={
            "code": ErrorCode.ODL_REQUEST_FAILED.value,
            "message": f"ODL request failed: {str(e)}",
            "details": getattr(e, "details", None),
        })
    if isinstance(e, asyncio.TimeoutError):
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail={
            "code": ErrorCode.ODL_TIMEOUT.value,
            "message": f"ODL request timeout during {operation}",
        })
    logger.error(f"Unexpected error in {operation}: {e}")
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={
        "code": ErrorCode.ODL_REQUEST_FAILED.value,
        "message": f"Unexpected error: {str(e)}",
    })


# ── POST endpoints — require ENGINEER+ ───────────────────────────────────────

@router.post("/devices/{node_id}/flows/connectivity/arp-flood", response_model=FlowResponse)
async def add_arp_flood_flow(
    node_id: str,
    request: ArpFloodRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """📡 ARP Flood — กระจาย ARP ทุกพอร์ต (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_arp_flood_flow(
            flow_id=request.flow_id, node_id=node_id,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.arp-flood")


@router.post("/devices/{node_id}/flows/connectivity/base", response_model=FlowResponse)
async def add_flow(
    node_id: str,
    request: FlowAddRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🔀 Base Connectivity — L1 Forwarding (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_flow(
            flow_id=request.flow_id, node_id=node_id,
            inbound_interface_id=request.inbound_interface_id,
            outbound_interface_id=request.outbound_interface_id,
            priority=request.priority, table_id=request.table_id,
            bidirectional=request.bidirectional,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.add")


@router.post("/devices/{node_id}/flows/connectivity/default-gateway", response_model=FlowResponse)
async def add_default_gateway_flow(
    node_id: str,
    request: DefaultGatewayRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🌐 Default Gateway (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_default_gateway_flow(
            flow_id=request.flow_id, node_id=node_id,
            outbound_interface_id=request.outbound_interface_id,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.default_gateway")


@router.post("/devices/{node_id}/flows/steering/l4-port", response_model=FlowResponse)
async def add_traffic_steer_flow(
    node_id: str,
    request: TrafficSteerRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🎯 Traffic Steering — L4 TCP/UDP Redirect (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_traffic_steer_flow(
            flow_id=request.flow_id, node_id=node_id,
            inbound_interface_id=request.inbound_interface_id,
            outbound_interface_id=request.outbound_interface_id,
            dst_port=request.dst_port, protocol=request.protocol,
            priority=request.priority, table_id=request.table_id,
            bidirectional=request.bidirectional,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.steer")


@router.post("/devices/{node_id}/flows/steering/l2-mac", response_model=FlowResponse)
async def add_mac_steer_flow(
    node_id: str,
    request: MacSteerRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🏷️ L2 MAC Steering (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_mac_steer_flow(
            flow_id=request.flow_id, node_id=node_id,
            src_mac=request.src_mac, outbound_interface_id=request.outbound_interface_id,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.steer.mac")


@router.post("/devices/{node_id}/flows/steering/l3-ip", response_model=FlowResponse)
async def add_ip_steer_flow(
    node_id: str,
    request: IpSteerRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🌐 L3 IP Steering (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_ip_steer_flow(
            flow_id=request.flow_id, node_id=node_id,
            dst_ip=request.dst_ip, outbound_interface_id=request.outbound_interface_id,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.steer.ip")


@router.post("/devices/{node_id}/flows/steering/l3-subnet", response_model=FlowResponse)
async def add_subnet_steer_flow(
    node_id: str,
    request: SubnetSteerRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🌐 L3 Subnet Steering (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_subnet_steer_flow(
            flow_id=request.flow_id, node_id=node_id,
            src_ip_subnet=request.src_ip_subnet, outbound_interface_id=request.outbound_interface_id,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.steer.subnet")


@router.post("/devices/{node_id}/flows/acl/block-mac", response_model=FlowResponse)
async def add_acl_mac_drop(
    node_id: str,
    request: AclMacDropRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🛑 L2 ACL — Drop by source MAC (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_acl_mac_drop(
            flow_id=request.flow_id, node_id=node_id,
            src_mac=request.src_mac, priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.acl.mac")


@router.post("/devices/{node_id}/flows/acl/block-ip", response_model=FlowResponse)
async def add_acl_ip_blacklist(
    node_id: str,
    request: AclIpBlacklistRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🛑 L3 ACL — Drop by IP pair (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_acl_ip_blacklist(
            flow_id=request.flow_id, node_id=node_id,
            src_ip=request.src_ip, dst_ip=request.dst_ip,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.acl.ip")


@router.post("/devices/{node_id}/flows/acl/block-port", response_model=FlowResponse)
async def add_acl_port_drop(
    node_id: str,
    request: AclPortDropRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🛑 L4 ACL — Drop by destination port (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_acl_port_drop(
            flow_id=request.flow_id, node_id=node_id,
            dst_port=request.dst_port, protocol=request.protocol,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.acl.port")


@router.post("/devices/{node_id}/flows/acl/whitelist-port", response_model=FlowResponse)
async def add_acl_whitelist(
    node_id: str,
    request: AclWhitelistRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """✅ Whitelist — allow specific port (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_acl_whitelist(
            flow_id=request.flow_id, node_id=node_id,
            dst_port=request.dst_port, protocol=request.protocol,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.acl.whitelist")


@router.post("/devices/{node_id}/flows/acl/icmp-control", response_model=FlowResponse)
async def add_icmp_control(
    node_id: str,
    request: IcmpControlRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🛑 L3 ICMP Control (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.add_icmp_control(
            flow_id=request.flow_id, node_id=node_id,
            action=request.action, priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.acl.icmp")


@router.post("/devices/{node_id}/flows/sync", response_model=FlowResponse)
async def sync_flow_rules(
    node_id: str,
    table_id: int = Query(default=0, ge=0, le=255),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🔄 Flow Sync — เทียบ DB กับ ODL (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.sync_flow_rules(node_id=node_id, table_id=table_id)
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.sync")


@router.post("/flow-rules/{flow_rule_id}/retry", response_model=FlowResponse)
async def retry_flow(
    flow_rule_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🔄 Retry FAILED Flow (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.retry_flow(flow_rule_id=flow_rule_id)
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow-rules.retry")


@router.post("/flow-rules/{flow_rule_id}/reactivate", response_model=FlowResponse)
async def reactivate_flow(
    flow_rule_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """✨ Reactivate DELETED Flow (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        result = await openflow_service.reactivate_flow(flow_rule_id=flow_rule_id)
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow-rules.reactivate")


# ── DELETE endpoints — require ADMIN+ ────────────────────────────────────────

@router.delete("/devices/{node_id}/flows/{flow_id}", response_model=FlowResponse)
async def delete_flow(
    node_id: str,
    flow_id: str,
    table_id: int = Query(default=0, ge=0, le=255),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🗑️ ลบ Flow Rule (requires ADMIN+)"""
    check_admin_permission(current_user)
    try:
        result = await openflow_service.delete_flow(flow_id=flow_id, node_id=node_id, table_id=table_id)
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.delete")


@router.delete("/devices/{node_id}/flows", response_model=FlowResponse)
async def reset_table(
    node_id: str,
    table_id: int = Query(default=0, ge=0, le=255),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """💥 Reset Table — ล้าง Flow Rules ทั้งหมด (requires ADMIN+)"""
    check_admin_permission(current_user)
    try:
        result = await openflow_service.reset_table(node_id=node_id, table_id=table_id)
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.reset")


@router.delete("/flow-rules/{flow_rule_id}", response_model=FlowResponse)
async def hard_delete_flow(
    flow_rule_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🗑️ Hard Delete Flow from DB (requires ADMIN+)"""
    check_admin_permission(current_user)
    try:
        result = await openflow_service.hard_delete_flow(flow_rule_id=flow_rule_id)
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow-rules.hard_delete")


# ── GET endpoints — require any authenticated user ────────────────────────────

@router.get("/devices/{node_id}/flows", response_model=FlowResponse)
async def get_flows(
    node_id: str,
    table_id: Optional[int] = Query(default=None, ge=0, le=255),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """📋 ดู OpenFlow Flow Rules ทั้งหมดของ Device (requires login)"""
    try:
        result = await openflow_service.get_flows(node_id=node_id, table_id=table_id)
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.get")


@router.get("/devices/{node_id}/flows/{flow_id}", response_model=FlowResponse)
async def get_flow_by_id(
    node_id: str,
    flow_id: str,
    table_id: int = Query(default=0, ge=0, le=255),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """🔍 ดู Flow เฉพาะตัว (requires login)"""
    try:
        result = await openflow_service.get_flow_by_id(node_id=node_id, flow_id=flow_id, table_id=table_id)
        return FlowResponse(success=True, code=ErrorCode.SUCCESS.value, message=result["message"], data=result)
    except Exception as e:
        _handle_flow_error(e, "flow.get.detail")


@router.get("/flows/templates", response_model=FlowTemplateResponse)
async def get_flow_templates(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """📋 Flow Templates (requires login)"""
    try:
        return openflow_service.get_flow_templates()
    except Exception as e:
        _handle_flow_error(e, "flow.templates")


@router.get("/flow-rules", response_model=FlowRuleListResponse)
async def get_flow_rules(
    node_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    flow_type: Optional[str] = Query(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """📋 Dashboard Flow List from DB (requires login)"""
    try:
        records = await openflow_service.get_flow_rules(node_id=node_id, status=status, flow_type=flow_type)
        items = [FlowRuleItem(**r) for r in records]
        return FlowRuleListResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=f"Found {len(items)} flow rule(s)",
            data=items, total=len(items),
        )
    except Exception as e:
        _handle_flow_error(e, "flow-rules.list")
