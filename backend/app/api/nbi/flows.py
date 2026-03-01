"""
NBI OpenFlow Flow Management Endpoints
สร้าง / ลบ / ดู OpenFlow Flow Rules ผ่าน ODL RESTCONF API

Endpoints:
  POST   /flows/arp-flood              - ARP Flood (1 call per switch)
  POST   /flows                        - Base Connectivity (bidirectional by default)
  POST   /flows/steer                  - Traffic Steering (bidirectional by default)
  POST   /flows/acl                    - ACL Drop (inbound only, 1 call)
  DELETE /flows/{flow_id}              - ลบ flow rule (ทุกประเภท)
  GET    /devices/{node_id}/flows      - ดู flow ทั้งหมดของ device
"""
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status
from app.services.openflow_service import OpenFlowService
from app.core.logging import logger
from app.core.errors import OdlRequestError

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


# ──────────────────────────────────────────────────────────────
# Shared Error Handler
# ──────────────────────────────────────────────────────────────
def _handle_flow_error(e: Exception, operation: str):
    """Shared error handler สำหรับทุก flow endpoint"""
    if isinstance(e, ValueError):
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

    if isinstance(e, OdlRequestError):
        logger.error(f"ODL request failed for {operation}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": ErrorCode.ODL_REQUEST_FAILED.value,
                "message": f"ODL request failed: {str(e)}",
                "details": getattr(e, "details", None),
            },
        )

    if isinstance(e, asyncio.TimeoutError):
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": ErrorCode.ODL_TIMEOUT.value,
                "message": f"ODL request timeout during {operation}",
            },
        )

    logger.error(f"Unexpected error in {operation}: {e}")
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": ErrorCode.ODL_REQUEST_FAILED.value,
            "message": f"Unexpected error: {str(e)}",
        },
    )


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/connectivity/arp-flood
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/connectivity/arp-flood", response_model=FlowResponse)
async def add_arp_flood_flow(node_id: str, request: ArpFloodRequest):
    """
    📡 ARP Flood — กระจาย ARP ทุกพอร์ต
    Match: `ethernet-type = 0x0806 (ARP)` → Action: `FLOOD`
    """
    try:
        result = await openflow_service.add_arp_flood_flow(
            flow_id=request.flow_id,
            node_id=node_id,
            priority=request.priority,
            table_id=request.table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.arp-flood")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/connectivity/base
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/connectivity/base", response_model=FlowResponse)
async def add_flow(node_id: str, request: FlowAddRequest):
    """🔀 Base Connectivity — L1 Forwarding"""
    try:
        result = await openflow_service.add_flow(
            flow_id=request.flow_id,
            node_id=node_id,
            inbound_interface_id=request.inbound_interface_id,
            outbound_interface_id=request.outbound_interface_id,
            priority=request.priority,
            table_id=request.table_id,
            bidirectional=request.bidirectional,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.add")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/connectivity/default-gateway
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/connectivity/default-gateway", response_model=FlowResponse)
async def add_default_gateway_flow(node_id: str, request: DefaultGatewayRequest):
    """🌐 Default Gateway — ทราฟฟิกที่ไม่ตรงกับกฎใดๆ ให้ส่งออกไปที่ Gateway"""
    try:
        result = await openflow_service.add_default_gateway_flow(
            flow_id=request.flow_id,
            node_id=node_id,
            outbound_interface_id=request.outbound_interface_id,
            priority=request.priority,
            table_id=request.table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.default_gateway")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/steering/l4-port
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/steering/l4-port", response_model=FlowResponse)
async def add_traffic_steer_flow(node_id: str, request: TrafficSteerRequest):
    """🎯 Traffic Steering — L4 TCP/UDP Redirect"""
    try:
        result = await openflow_service.add_traffic_steer_flow(
            flow_id=request.flow_id,
            node_id=node_id,
            inbound_interface_id=request.inbound_interface_id,
            outbound_interface_id=request.outbound_interface_id,
            dst_port=request.dst_port,
            protocol=request.protocol,
            priority=request.priority,
            table_id=request.table_id,
            bidirectional=request.bidirectional,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.steer")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/steering/l2-mac
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/steering/l2-mac", response_model=FlowResponse)
async def add_mac_steer_flow(node_id: str, request: MacSteerRequest):
    """🏷️ L2 MAC Steering — redirect traffic จาก source MAC เฉพาะเครื่อง"""
    try:
        result = await openflow_service.add_mac_steer_flow(
            flow_id=request.flow_id,
            node_id=node_id,
            src_mac=request.src_mac,
            outbound_interface_id=request.outbound_interface_id,
            priority=request.priority,
            table_id=request.table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.steer.mac")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/steering/l3-ip
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/steering/l3-ip", response_model=FlowResponse)
async def add_ip_steer_flow(node_id: str, request: IpSteerRequest):
    """🌐 L3 IP Steering — redirect traffic ไปหา destination IP"""
    try:
        result = await openflow_service.add_ip_steer_flow(
            flow_id=request.flow_id,
            node_id=node_id,
            dst_ip=request.dst_ip,
            outbound_interface_id=request.outbound_interface_id,
            priority=request.priority,
            table_id=request.table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.steer.ip")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/steering/l3-subnet
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/steering/l3-subnet", response_model=FlowResponse)
async def add_subnet_steer_flow(node_id: str, request: SubnetSteerRequest):
    """🌐 L3 Subnet Steering — redirect traffic ตามวง Source IP"""
    try:
        result = await openflow_service.add_subnet_steer_flow(
            flow_id=request.flow_id,
            node_id=node_id,
            src_ip_subnet=request.src_ip_subnet,
            outbound_interface_id=request.outbound_interface_id,
            priority=request.priority,
            table_id=request.table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.steer.subnet")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/acl/block-mac
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/acl/block-mac", response_model=FlowResponse)
async def add_acl_mac_drop(node_id: str, request: AclMacDropRequest):
    """🛑 L2 ACL — Drop traffic จาก source MAC เฉพาะเครื่อง"""
    try:
        result = await openflow_service.add_acl_mac_drop(
            flow_id=request.flow_id, node_id=node_id,
            src_mac=request.src_mac, priority=request.priority,
            table_id=request.table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.acl.mac")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/acl/block-ip
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/acl/block-ip", response_model=FlowResponse)
async def add_acl_ip_blacklist(node_id: str, request: AclIpBlacklistRequest):
    """🛑 L3 ACL — Drop traffic ระหว่าง source IP กับ destination IP"""
    try:
        result = await openflow_service.add_acl_ip_blacklist(
            flow_id=request.flow_id, node_id=node_id,
            src_ip=request.src_ip, dst_ip=request.dst_ip,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.acl.ip")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/acl/block-port
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/acl/block-port", response_model=FlowResponse)
async def add_acl_port_drop(node_id: str, request: AclPortDropRequest):
    """🛑 L4 ACL — Drop traffic ที่ไปหา destination port (TCP/UDP)"""
    try:
        result = await openflow_service.add_acl_port_drop(
            flow_id=request.flow_id, node_id=node_id,
            dst_port=request.dst_port, protocol=request.protocol,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.acl.port")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/acl/whitelist-port
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/acl/whitelist-port", response_model=FlowResponse)
async def add_acl_whitelist(node_id: str, request: AclWhitelistRequest):
    """✅ Whitelist — อนุญาตเฉพาะ port ที่กำหนด (TCP/UDP, action: NORMAL)"""
    try:
        result = await openflow_service.add_acl_whitelist(
            flow_id=request.flow_id, node_id=node_id,
            dst_port=request.dst_port, protocol=request.protocol,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.acl.whitelist")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/acl/icmp-control
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/acl/icmp-control", response_model=FlowResponse)
async def add_icmp_control(node_id: str, request: IcmpControlRequest):
    """🛑 L3 ICMP Control — บล็อกหรืออนุญาตการ Ping"""
    try:
        result = await openflow_service.add_icmp_control(
            flow_id=request.flow_id, node_id=node_id,
            action=request.action,
            priority=request.priority, table_id=request.table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.acl.icmp")


# ──────────────────────────────────────────────────────────────
# DELETE /devices/{node_id}/flows/{flow_id}  →  ลบ Flow Rule
# ──────────────────────────────────────────────────────────────
@router.delete("/devices/{node_id}/flows/{flow_id}", response_model=FlowResponse)
async def delete_flow(
    node_id: str,
    flow_id: str,
    table_id: int = Query(default=0, ge=0, le=255, description="Flow Table ID"),
):
    """🗑️ ลบ Flow Rule (ใช้ได้ทุกประเภท)"""
    try:
        result = await openflow_service.delete_flow(
            flow_id=flow_id, node_id=node_id, table_id=table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.delete")


# ──────────────────────────────────────────────────────────────
# DELETE /devices/{node_id}/flows  →  ล้าง Flows ทั้ง table
# ──────────────────────────────────────────────────────────────
@router.delete("/devices/{node_id}/flows", response_model=FlowResponse)
async def reset_table(
    node_id: str,
    table_id: int = Query(default=0, ge=0, le=255, description="Flow Table ID"),
):
    """💥 Reset Table — ล้าง Flow Rules ทั้งหมดใน table"""
    try:
        result = await openflow_service.reset_table(
            node_id=node_id, table_id=table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.reset")


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
    """📋 ดู OpenFlow Flow Rules ทั้งหมดของ Device"""
    try:
        result = await openflow_service.get_flows(
            node_id=node_id, table_id=table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.get")


# ──────────────────────────────────────────────────────────────
# GET /devices/{node_id}/flows/{flow_id}  →  ดู Flow เฉพาะตัว
# ──────────────────────────────────────────────────────────────
@router.get("/devices/{node_id}/flows/{flow_id}", response_model=FlowResponse)
async def get_flow_by_id(
    node_id: str,
    flow_id: str,
    table_id: int = Query(default=0, ge=0, le=255, description="Flow Table ID"),
):
    """
    🔍 ดู Flow เฉพาะตัว — ดึงรายละเอียดเชิงลึกจาก ODL

    ใช้เมื่อกดที่รายการ Flow บน Dashboard เพื่อดู Match/Action details
    """
    try:
        result = await openflow_service.get_flow_by_id(
            node_id=node_id, flow_id=flow_id, table_id=table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.get.detail")


# ──────────────────────────────────────────────────────────────
# GET /flows/templates  →  Flow Templates Metadata (frontend UI)
# ──────────────────────────────────────────────────────────────
@router.get("/flows/templates", response_model=FlowTemplateResponse)
async def get_flow_templates():
    """
    📋 Flow Templates — Metadata สำหรับวาด UI สร้าง Flow
    ส่งคืน หมวดหมู่ > Templates > ฟิลด์ที่จำเป็น สำหรับสร้าง frontend wizard
    """
    try:
        return openflow_service.get_flow_templates()
    except Exception as e:
        _handle_flow_error(e, "flow.templates")


# ──────────────────────────────────────────────────────────────
# POST /devices/{node_id}/flows/sync  →  Sync DB ↔ ODL
# ──────────────────────────────────────────────────────────────
@router.post("/devices/{node_id}/flows/sync", response_model=FlowResponse)
async def sync_flow_rules(
    node_id: str,
    table_id: int = Query(default=0, ge=0, le=255, description="Flow Table ID"),
):
    """
    🔄 Flow Sync — เทียบ DB กับ ODL ตรวจจับ zombie/unmanaged

    - **zombie**: DB ยัง ACTIVE แต่ ODL ไม่มี → auto mark DELETED
    - **unmanaged**: ODL มี flow แต่ DB ไม่มี → report (ไม่ได้สร้างผ่าน Backend)

    ใช้สำหรับปุ่ม **"Sync Flows"** บนหน้า Dashboard
    """
    try:
        result = await openflow_service.sync_flow_rules(
            node_id=node_id, table_id=table_id,
        )
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow.sync")


# ──────────────────────────────────────────────────────────────
# GET /flow-rules  →  Dashboard Flow List (from DB)
# ──────────────────────────────────────────────────────────────
@router.get("/flow-rules", response_model=FlowRuleListResponse)
async def get_flow_rules(
    node_id: Optional[str] = Query(default=None, description="Filter by node_id"),
    status: Optional[str] = Query(default=None, description="Filter by status: ACTIVE, PENDING, FAILED, DELETED"),
    flow_type: Optional[str] = Query(default=None, description="Filter by flow_type"),
):
    """
    📋 Dashboard Flow List — ดึง Flow Rules จาก DB (structured, fast)

    ใช้แสดง flow list บนหน้า Dashboard พร้อม status, type, created_at
    """
    try:
        records = await openflow_service.get_flow_rules(
            node_id=node_id, status=status, flow_type=flow_type,
        )
        items = [FlowRuleItem(**r) for r in records]
        return FlowRuleListResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=f"Found {len(items)} flow rule(s)",
            data=items, total=len(items),
        )
    except Exception as e:
        _handle_flow_error(e, "flow-rules.list")


# ──────────────────────────────────────────────────────────────
# POST /flow-rules/{id}/retry  →  Retry FAILED Flow
# ──────────────────────────────────────────────────────────────
@router.post("/flow-rules/{flow_rule_id}/retry", response_model=FlowResponse)
async def retry_flow(flow_rule_id: str):
    """
    🔄 Retry FAILED Flow — ลอง PUT ไป ODL อีกครั้ง

    ใช้เมื่อ flow มี status=FAILED แล้วต้องการลองใหม่
    """
    try:
        result = await openflow_service.retry_flow(flow_rule_id=flow_rule_id)
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow-rules.retry")

# ──────────────────────────────────────────────────────────────
# POST /flow-rules/{id}/reactivate  →  Reactivate DELETED Flow
# ──────────────────────────────────────────────────────────────
@router.post("/flow-rules/{flow_rule_id}/reactivate", response_model=FlowResponse)
async def reactivate_flow(flow_rule_id: str):
    """
    ✨ Reactivate DELETED Flow — เปิดใช้งาน Flow ที่เคยลบไปแล้วกลับมาใหม่

    ใช้เมื่อ flow ถูกลบออกจาก ODL ไปแล้ว (Status = DELETED) แต่ต้องการนำประวัติเดิม
    ที่เคยเก็บใน Database ขึ้นมาใช้งาน (Deploy) บน ODL อีกครั้ง
    """
    try:
        result = await openflow_service.reactivate_flow(flow_rule_id=flow_rule_id)
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow-rules.reactivate")

# ──────────────────────────────────────────────────────────────
# DELETE /flow-rules/{id}  →  Hard Delete Flow from DB
# ──────────────────────────────────────────────────────────────
@router.delete("/flow-rules/{flow_rule_id}", response_model=FlowResponse)
async def hard_delete_flow(flow_rule_id: str):
    """
    🗑️ Hard Delete Flow — ลบประวัติ Flow ออกจาก Database ถาวร

    ใช้สำหรับลบ Flow Rule ที่ผู้ใช้ไม่ต้องการเก็บประวัติไว้อีกต่อไป
    (ข้อมูลจะหายไปจากตาราง Flow เลย ไม่สามารถ Reactivate ได้อีก)
    """
    try:
        result = await openflow_service.hard_delete_flow(flow_rule_id=flow_rule_id)
        return FlowResponse(
            success=True, code=ErrorCode.SUCCESS.value,
            message=result["message"], data=result,
        )
    except Exception as e:
        _handle_flow_error(e, "flow-rules.hard_delete")
