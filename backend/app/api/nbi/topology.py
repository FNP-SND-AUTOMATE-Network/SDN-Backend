import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Any, Dict
from app.normalizers.topology import normalize_topology

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


@router.get("/topology", response_model=TopologyResponse)
def get_hybrid_topology():
    topology_map = {
        "nodes": set(),
        "links": []
    }

    AUTH = (settings.ODL_USERNAME, settings.ODL_PASSWORD)
    HEADERS = {'Accept': 'application/json'}
    TIMEOUT = settings.ODL_TIMEOUT_SEC

    # =========================================================
    # ส่วนที่ 1: ดึงโครงสร้าง Switch (OpenFlow)
    # =========================================================
    flow_url = f"{settings.ODL_BASE_URL}/rests/data/network-topology:network-topology/topology=flow:1?content=nonconfig"
    
    try:
        res_flow = requests.get(flow_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
        
        if res_flow.status_code == 401:
            raise HTTPException(status_code=500, detail="ODL Authentication Failed")
        
        if res_flow.status_code == 200:
            flow_data = res_flow.json()
            topo_list = flow_data.get("network-topology:topology", flow_data.get("topology", []))
            
            if topo_list:
                topo_obj = topo_list[0]
                
                # 1.1 ดึงชื่อโหนด OpenFlow มาเก็บไว้ (เช่น openflow:1, openflow:2)
                for node in topo_obj.get("node", []):
                    topology_map["nodes"].add(node["node-id"])
                
                # 1.2 ดึงเส้น Link ระหว่าง Switch
                for link in topo_obj.get("link", []):
                    source_tp = link.get("source", {}).get("source-tp")
                    dest_tp = link.get("destination", {}).get("dest-tp")
                    
                    if source_tp and dest_tp:
                        topology_map["links"].append({
                            "source": source_tp,
                            "target": dest_tp,
                            "type": "OpenFlow-L2"
                        })
        else:
            pass # Ignore API error
            
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=503, 
            detail=f"Service Unavailable: Cannot connect to ODL Controller. Details: {e}"
        )

    # =========================================================
    # ส่วนที่ 2: ดึงการเชื่อมต่อ Router (OpenConfig LLDP + Fallback)
    # =========================================================
    topology_map["nodes"].add("CSR1000vT") 
    
    router_links = []
    openconfig_url = f"{settings.ODL_BASE_URL}/rests/data/network-topology:network-topology/topology=topology-netconf/node=CSR1000vT/yang-ext:mount/openconfig-lldp:lldp/interfaces?content=nonconfig"
    
    try:
        # ลองท่าที่ 1: OpenConfig
        res_oc = requests.get(openconfig_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
        if res_oc.status_code == 200:
            oc_data = res_oc.json()
            interfaces = oc_data.get("openconfig-lldp:interfaces", {}).get("interface", [])
            for intf in interfaces:
                local_port = intf.get("name")
                for neighbor in intf.get("neighbors", {}).get("neighbor", []):
                    state = neighbor.get("state", {})
                    remote_node = state.get("system-name")
                    remote_port = state.get("port-id")
                    if remote_node and remote_port:
                        router_links.append({
                            "source": f"CSR1000vT:{local_port}",
                            "target": f"{remote_node}:{remote_port}",
                            "type": "NETCONF-LLDP (OpenConfig)"
                        })
        else:
            raise Exception(f"Status {res_oc.status_code}")
            
    except Exception as e:
        # ลองท่าที่ 2: Fallback ไป Cisco IOS-XE
        iosxe_url = f"{settings.ODL_BASE_URL}/rests/data/network-topology:network-topology/topology=topology-netconf/node=CSR1000vT/yang-ext:mount/Cisco-IOS-XE-lldp-oper:lldp-entries?content=nonconfig"
        try:
            res_ios = requests.get(iosxe_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
            if res_ios.status_code == 200:
                ios_data = res_ios.json()
                entries = ios_data.get("Cisco-IOS-XE-lldp-oper:lldp-entries", {}).get("lldp-entry", [])
                for entry in entries:
                    router_links.append({
                        "source": f"CSR1000vT:{entry.get('local-interface')}",
                        "target": f"{entry.get('device-id')}:{entry.get('connecting-interface')}",
                        "type": "NETCONF-LLDP (Cisco Native)"
                    })
        except Exception as ex:
            pass # Ignore Router LLDP entirely

    # นำเส้น Link ของ Router ไปต่อท้ายเส้น Link ของ Switch
    topology_map["links"].extend(router_links)

    # แปลง Set ให้เป็น List เพื่อให้ Pydantic/FastAPI แปลงเป็น JSON ได้ (Set จะไม่ถูกรองรับแบบ Default)
    topology_map["nodes"] = list(topology_map["nodes"])
    
    # Normalize data for frontend
    normalized_data = normalize_topology(topology_map)
    
    return normalized_data
