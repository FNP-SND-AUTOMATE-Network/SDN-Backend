from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from app.services.topology_sync import sync_odl_topology_to_db
from app.services.topology_binding_service import (
    delete_lldp_binding,
    list_lldp_bindings,
    upsert_lldp_binding,
)
from app.core.logging import logger
from app.api.users import get_current_user, check_engineer_permission, check_admin_permission

router = APIRouter()


# ── Pydantic Models ───────────────────────────────────────────────────────────
class TopologyNodeResponse(BaseModel):
    id: str
    label: str
    type: str
    management_protocol: Optional[str] = None
    vendor: Optional[str] = None
    ip_address: Optional[str] = None
    status: Optional[str] = None

class TopologyLinkResponse(BaseModel):
    id: str
    source: str
    target: str
    sourcePort: str
    targetPort: str
    sourceTP: str
    targetTP: str
    type: str

class TopologyResponse(BaseModel):
    nodes: List[TopologyNodeResponse]
    links: List[TopologyLinkResponse]

class TopologySyncResponse(BaseModel):
    success: bool
    message: str
    stats: Dict[str, Any]

class LldpBindingRequest(BaseModel):
    chassis_id: str
    node_id: str

class LldpBindingResponse(BaseModel):
    id: str
    chassis_id_norm: str
    node_id: str
    created_at: Any
    updated_at: Any


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/topology/sync", response_model=TopologySyncResponse)
async def trigger_topology_sync(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Trigger manual Topology sync from ODL to DB (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    try:
        stats = await sync_odl_topology_to_db()
        return TopologySyncResponse(success=True, message="Topology synchronized successfully.", stats=stats)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to sync topology: {str(e)}")


@router.get("/topology", response_model=TopologyResponse)
async def get_hybrid_topology(
    local_site_id: Optional[str] = Query(None, description="Filter topology by local site ID"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """ดึงข้อมูล Topology ล่าสุดจาก Database (requires login)"""
    from app.database import get_prisma_client
    prisma = get_prisma_client()

    try:
        query_filter: Dict[str, Any] = {"node_id": {"not": None}}
        if local_site_id:
            query_filter["local_site_id"] = local_site_id

        devices = await prisma.devicenetwork.find_many(where=query_filter)

        nodes: List[TopologyNodeResponse] = []
        valid_device_ids: set = set()

        for d in devices:
            valid_device_ids.add(d.id)
            dtype = "switch"
            if d.type in ("ROUTER", "FIREWALL"):
                dtype = d.type.lower()
            nodes.append(TopologyNodeResponse(
                id=d.node_id,
                label=d.device_name or d.node_id,
                type=dtype,
                management_protocol=d.management_protocol,
                vendor=d.vendor,
                ip_address=d.ip_address,
                status=d.status,
            ))

        logger.debug(f"[GET topology] {len(nodes)} nodes, valid_device_ids={len(valid_device_ids)}")

        link_where: Dict[str, Any] = {}
        if local_site_id and valid_device_ids:
            site_intfs = await prisma.interface.find_many(
                where={"device_id": {"in": list(valid_device_ids)}},
            )
            site_intf_ids = [i.id for i in site_intfs]
            link_where = {
                "source_interface_id": {"in": site_intf_ids},
                "target_interface_id": {"in": site_intf_ids},
            }

        links_raw = await prisma.link.find_many(
            where=link_where,
            include={
                "source": {"include": {"device": True}},
                "target": {"include": {"device": True}},
            }
        )

        seen_pairs: set = set()
        links: List[TopologyLinkResponse] = []

        for link in links_raw:
            src_intf = link.source
            tgt_intf = link.target
            if not src_intf or not tgt_intf:
                continue
            src_device = src_intf.device
            tgt_device = tgt_intf.device
            if not src_device or not tgt_device:
                continue
            if not src_device.node_id or not tgt_device.node_id:
                continue

            src_node = src_device.node_id
            tgt_node = tgt_device.node_id
            src_port = src_intf.name
            tgt_port = tgt_intf.name
            src_tp = src_intf.tp_id or f"{src_node}:{src_port}"
            tgt_tp = tgt_intf.tp_id or f"{tgt_node}:{tgt_port}"

            pair_key = tuple(sorted([(src_node, src_port), (tgt_node, tgt_port)]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            link_type = "OPENFLOW" if (
                src_device.management_protocol == "OPENFLOW" and
                tgt_device.management_protocol == "OPENFLOW"
            ) else "NETCONF"

            links.append(TopologyLinkResponse(
                id=link.link_id,
                source=src_node,
                target=tgt_node,
                sourcePort=src_port,
                targetPort=tgt_port,
                sourceTP=src_tp,
                targetTP=tgt_tp,
                type=link_type,
            ))

        logger.info(f"[GET topology] Returning {len(nodes)} nodes, {len(links)} links")
        return TopologyResponse(nodes=nodes, links=links)

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/topology/lldp-bindings", response_model=List[LldpBindingResponse])
async def get_lldp_bindings(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Get LLDP chassis-to-node bindings (requires login)"""
    from app.database import get_prisma_client
    prisma = get_prisma_client()
    try:
        rows = await list_lldp_bindings(prisma)
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list bindings: {str(e)}")


@router.post("/topology/lldp-bindings", response_model=LldpBindingResponse)
async def create_or_update_lldp_binding(
    payload: LldpBindingRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Create or update an LLDP binding (requires ENGINEER+)"""
    check_engineer_permission(current_user)
    from app.database import get_prisma_client
    prisma = get_prisma_client()
    try:
        row = await upsert_lldp_binding(prisma, chassis_id=payload.chassis_id, node_id=payload.node_id)
        return row
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upsert binding: {str(e)}")


@router.delete("/topology/lldp-bindings/{chassis_id}", response_model=LldpBindingResponse)
async def remove_lldp_binding(
    chassis_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Delete an LLDP binding (requires ADMIN+)"""
    check_admin_permission(current_user)
    from app.database import get_prisma_client
    prisma = get_prisma_client()
    try:
        row = await delete_lldp_binding(prisma, chassis_id=chassis_id)
        return row
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete binding: {str(e)}")
