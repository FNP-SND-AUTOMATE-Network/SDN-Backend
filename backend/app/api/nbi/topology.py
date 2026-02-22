import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Any, Dict, Optional
from app.normalizers.topology import normalize_topology
from app.services.topology_sync import sync_odl_topology_to_db

from app.core.config import settings

router = APIRouter()

# ==========================================
# 📦 Pydantic Models (Response Schemas)
# ==========================================
class LinkModel(BaseModel):
    source: str
    target: str
    type: str

class TopologyResponse(BaseModel):
    nodes: List[Dict[str, Any]]
    links: List[Dict[str, Any]]


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
    """
    from app.database import get_prisma_client
    prisma = get_prisma_client()
    
    topology_map = {
        "nodes": [],
        "links": []
    }

    try:
        # =========================================================
        # 1. ค้นหา Devices (Nodes)
        # =========================================================
        query_filter = {}
        if local_site_id:
            query_filter["local_site_id"] = local_site_id
            
        devices = await prisma.devicenetwork.find_many(
            where=query_filter
        )
        
        valid_node_ids = set()
        for d in devices:
            if d.node_id:
                valid_node_ids.add(d.node_id)
                
                # Fetch interfaces for this device to show as standalone nodes if needed
                interfaces = await prisma.interface.find_many(where={"device_id": d.id})
                
                # Add the device itself to the nodes list
                topology_map["nodes"].append({
                    "id": d.node_id,
                    "label": d.node_name or d.node_id,
                    "type": "router" if d.type in ["ROUTER", "FIREWALL"] else "switch"
                })
                
                # Optionally add interfaces as sub-nodes or isolated nodes
                for intf in interfaces:
                    intf_id = intf.tp_id or f"{d.node_id}:{intf.name}"
                    topology_map["nodes"].append({
                        "id": intf_id,
                        "label": intf.name,
                        "type": "interface",
                        "parent": d.node_id
                    })
                
        # =========================================================
        # 2. ค้นหา Links ที่เกี่ยวข้อง
        # =========================================================
        # ดึง Link ทั้งหมดที่มี Source/Target Interface ผูกกับ Device เหล่านี้
        links = await prisma.link.find_many(
            include={
                "source": { "include": { "device": True } },
                "target": { "include": { "device": True } }
            }
        )
        
        for link in links:
            src_node_id = link.source.device.node_id
            tgt_node_id = link.target.device.node_id
            
            # กรอง Link: จะต้องมี Node_id ครบ และต้องอยู่ในเงื่อนไข site ของเรา (ถ้ามีการส่ง local_site_id มา)
            if not src_node_id or not tgt_node_id:
                continue
                
            if local_site_id:
                if src_node_id not in valid_node_ids or tgt_node_id not in valid_node_ids:
                    continue
            
            # เตรียม Source/Target TP ID (หากไม่มี ใช้ port name เป็น Fallback สำหรับวาดกราฟ)
            src_tp = link.source.tp_id or f"{src_node_id}:{link.source.name}"
            tgt_tp = link.target.tp_id or f"{tgt_node_id}:{link.target.name}"
            protocol_type = f"{link.source.device.management_protocol}-L2"
                
            topology_map["links"].append({
                "source": src_tp,
                "target": tgt_tp,
                "type": protocol_type
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    # Normalize data for frontend
    normalized_data = normalize_topology(topology_map)
    
    return normalized_data
