from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Any, Dict, Optional
from app.services.topology_sync import sync_odl_topology_to_db
from app.core.logging import logger

router = APIRouter()

# ==========================================
# Pydantic Models (Response Schemas)
# ==========================================
class TopologyNodeResponse(BaseModel):
    id: str
    label: str
    type: str  # "switch" | "router" | "firewall"
    management_protocol: Optional[str] = None
    vendor: Optional[str] = None
    ip_address: Optional[str] = None
    status: Optional[str] = None

class TopologyLinkResponse(BaseModel):
    id: str
    source: str           # source node_id
    target: str           # target node_id
    sourcePort: str       # source interface name
    targetPort: str       # target interface name
    sourceTP: str         # raw tp_id (e.g. openflow:1:1)
    targetTP: str         # raw tp_id
    type: str             # "OPENFLOW" | "NETCONF"

class TopologyResponse(BaseModel):
    nodes: List[TopologyNodeResponse]
    links: List[TopologyLinkResponse]

class TopologySyncResponse(BaseModel):
    success: bool
    message: str
    stats: Dict[str, int]


@router.post("/topology/sync", response_model=TopologySyncResponse)
async def trigger_topology_sync():
    """
    Trigger a manual synchronization of the Topology from ODL to the Prisma Database.
    This fetches nodes, interface ports, and links and upserts them.
    """
    try:
        stats = await sync_odl_topology_to_db()
        return TopologySyncResponse(
            success=True,
            message="Topology synchronized successfully.",
            stats=stats
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to sync topology: {str(e)}")


@router.get("/topology", response_model=TopologyResponse)
async def get_hybrid_topology(
    local_site_id: Optional[str] = Query(None, description="Filter topology by local site ID")
):
    """
    ดึงข้อมูล Topology ล่าสุดจาก Database (ที่ Sync ลงมาแล้ว)
    คืน nodes (devices) และ links (เส้นเชื่อมระหว่าง interfaces) สำหรับวาดกราฟ
    """
    from app.database import get_prisma_client
    prisma = get_prisma_client()

    try:
        # =========================================================
        # 1. ค้นหา Devices (Nodes) ที่มี node_id
        # =========================================================
        query_filter: Dict[str, Any] = {"node_id": {"not": None}}
        if local_site_id:
            query_filter["local_site_id"] = local_site_id

        devices = await prisma.devicenetwork.find_many(where=query_filter)

        nodes: List[TopologyNodeResponse] = []
        valid_device_ids: set = set()   # device.id (UUID) ที่ผ่านเงื่อนไข

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

        # =========================================================
        # 2. ค้นหา Links พร้อม Include source/target interface + device
        # =========================================================
        # กรณีมี site filter → ดึงเฉพาะ links ที่ทั้ง 2 ฝั่งอยู่ใน site (DB-level)
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
            logger.debug(f"[GET topology] site filter: {len(site_intf_ids)} interfaces for {len(valid_device_ids)} devices")

        links_raw = await prisma.link.find_many(
            where=link_where,
            include={
                "source": {"include": {"device": True}},
                "target": {"include": {"device": True}},
            }
        )

        seen_pairs: set = set()   # deduplicate bidirectional (safety net)
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

            # Deduplicate bidirectional links (A→B == B→A)
            pair_key = tuple(sorted([(src_node, src_port), (tgt_node, tgt_port)]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            # Determine link protocol type
            link_type = "OPENFLOW" if src_device.management_protocol == "OPENFLOW" and tgt_device.management_protocol == "OPENFLOW" else "NETCONF"

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
