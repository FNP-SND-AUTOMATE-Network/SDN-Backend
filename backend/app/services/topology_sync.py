"""
Service for syncing Topology from OpenDaylight to Database (Prisma)
"""
import requests
from typing import Dict, Any, List, Set, Tuple
from app.core.config import settings
from app.core.logging import logger
from app.database import get_prisma_client

async def sync_odl_topology_to_db() -> Dict[str, Any]:
    """
    ดึงข้อมูล Topology จาก ODL (OpenFlow & NETCONF) และ Upsert ลง Database ให้ทันสมัยที่สุด
    คืนค่าสรุปผลการ Sync
    """
    prisma = get_prisma_client()
    
    # Credentials ODL
    AUTH = (settings.ODL_USERNAME, settings.ODL_PASSWORD)
    HEADERS = {'Accept': 'application/json'}
    TIMEOUT = settings.ODL_TIMEOUT_SEC
    
    # ---------------------------------------------------------
    # 1. รวบรวมข้อมูลดิบ (Raw Data) จาก ODL ก่อน
    # ---------------------------------------------------------
    raw_nodes = set()
    raw_links: List[Dict[str, str]] = []
    
    # 1.1) ดึง Switch (OpenFlow)
    flow_url = f"{settings.ODL_BASE_URL}/rests/data/network-topology:network-topology/topology=flow:1?content=nonconfig"
    try:
        res_flow = requests.get(flow_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
        if res_flow.status_code == 200:
            flow_data = res_flow.json()
            topo_list = flow_data.get("network-topology:topology", flow_data.get("topology", []))
            if topo_list:
                topo_obj = topo_list[0]
                
                # Nodes OpenFlow
                for node in topo_obj.get("node", []):
                    raw_nodes.add(node["node-id"])
                
                # Links OpenFlow
                for link in topo_obj.get("link", []):
                    source_tp = link.get("source", {}).get("source-tp")
                    dest_tp = link.get("destination", {}).get("dest-tp")
                    link_id = link.get("link-id", f"{source_tp}-to-{dest_tp}")
                    if source_tp and dest_tp:
                        raw_links.append({
                            "link_id": link_id,
                            "source": source_tp,
                            "target": dest_tp,
                            "type": "OPENFLOW"
                        })
    except Exception as e:
        logger.error(f"Failed to fetch OpenFlow Topology from ODL: {e}")

    # 1.2) ดึง Router (NETCONF) แบบ Dynamic จาก DB
    try:
        netconf_devices = await prisma.devicenetwork.find_many(
            where={
                "management_protocol": "NETCONF",
                "node_id": {"not": None}
            }
        )
        for device in netconf_devices:
            node_id = device.node_id
            if not node_id: continue
            
            # ลองดึง LLDP ผ่าน OpenConfig
            oc_url = f"{settings.ODL_BASE_URL}/rests/data/network-topology:network-topology/topology=topology-netconf/node={node_id}/yang-ext:mount/openconfig-lldp:lldp/interfaces?content=nonconfig"
            
            try:
                res_oc = requests.get(oc_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
                if res_oc.status_code == 200:
                    raw_nodes.add(node_id) # การันตีว่ามีตัวตนใน topology แน่นอน
                    oc_data = res_oc.json()
                    interfaces = oc_data.get("openconfig-lldp:interfaces", {}).get("interface", [])
                    for intf in interfaces:
                        local_port = intf.get("name")
                        for neighbor in intf.get("neighbors", {}).get("neighbor", []):
                            state = neighbor.get("state", {})
                            remote_node = state.get("system-name")
                            remote_port = state.get("port-id")
                            
                            if remote_node and remote_port:
                                # Clean domain from system-name (e.g., CSR1000vT.lab.local -> CSR1000vT)
                                remote_node_clean = remote_node.split('.')[0]
                                
                                # Expand interface name abbreviations
                                remote_port_clean = remote_port
                                if remote_port_clean.startswith("Gi") and not remote_port_clean.startswith("Gigabit"):
                                    remote_port_clean = remote_port_clean.replace("Gi", "GigabitEthernet", 1)
                                elif remote_port_clean.startswith("Te") and not remote_port_clean.startswith("Ten"):
                                    remote_port_clean = remote_port_clean.replace("Te", "TenGigabitEthernet", 1)
                                elif remote_port_clean.startswith("Fa") and not remote_port_clean.startswith("Fast"):
                                    remote_port_clean = remote_port_clean.replace("Fa", "FastEthernet", 1)
                                elif remote_port_clean.startswith("Eth") and not remote_port_clean.startswith("Ethernet"):
                                    remote_port_clean = remote_port_clean.replace("Eth", "Ethernet", 1)

                                raw_links.append({
                                    "link_id": f"{node_id}:{local_port}-to-{remote_node_clean}:{remote_port_clean}",
                                    "source": f"{node_id}:{local_port}",
                                    "target": f"{remote_node_clean}:{remote_port_clean}",
                                    "type": "NETCONF"
                                })
                else:
                    # Fallback ไป Cisco IOS-XE ทันทีถ้าไม่ได้
                    raise Exception("Try Cisco IOS-XE")
            except Exception:
                iosxe_url = f"{settings.ODL_BASE_URL}/rests/data/network-topology:network-topology/topology=topology-netconf/node={node_id}/yang-ext:mount/Cisco-IOS-XE-lldp-oper:lldp-entries?content=nonconfig"
                try:
                    res_ios = requests.get(iosxe_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
                    if res_ios.status_code == 200:
                        raw_nodes.add(node_id)
                        ios_data = res_ios.json()
                        entries = ios_data.get("Cisco-IOS-XE-lldp-oper:lldp-entries", {}).get("lldp-entry", [])
                        for entry in entries:
                            remote_id = entry.get('device-id')
                            local_intf = entry.get('local-interface')
                            remote_intf = entry.get('connecting-interface')
                            
                            raw_links.append({
                                "link_id": f"{node_id}:{local_intf}-to-{remote_id}:{remote_intf}",
                                "source": f"{node_id}:{local_intf}",
                                "target": f"{remote_id}:{remote_intf}",
                                "type": "NETCONF"
                            })
                except Exception as ex:
                    logger.warning(f"Failed to fetch LLDP from {node_id}: {ex}")
    except Exception as e:
        logger.error(f"Failed to query NETCONF devices from DB: {e}")

    # ---------------------------------------------------------
    # 2. เริ่มขั้นตอนเขียนลง DB แบบ Upsert
    # ---------------------------------------------------------
    stats = {"nodes_synced": 0, "interfaces_synced": 0, "links_synced": 0}
    
    # 2.1) Upsert Nodes (DeviceNetwork)
    # สำหรับ OpenFlow เราสร้างอุปกรณ์ใหม่ ถ้าไม่มีในระบบ
    # ส่วน NETCONF จะอิงอันที่มีอยู่ เพราะต้องใส่ IP/Pass มาก่อนหน้านี้แล้ว
    device_id_map: Dict[str, str] = {} # node_id -> device.id (UUID)
    
    for node_id in raw_nodes:
        # หากขึ้นต้นด้วย openflow ให้ใส่ค่า Default ที่เหมาะสมได้
        if node_id.startswith("openflow:"):
            datapath_id = node_id.split(":")[-1] if ":" in node_id else None
            
            device = await prisma.devicenetwork.upsert(
                where={"node_id": node_id},
                data={
                    "create": {
                        "node_id": node_id,
                        "device_name": node_id,
                        # การสุ่มหรือสร้าง field ที่ให้ค่า unique เบื้องต้น (จำลอง)
                        "serial_number": f"OF-SN-{node_id}",
                        "mac_address": f"OF-MAC-{node_id}",
                        "device_model": "OpenFlow Switch",
                        "type": "SWITCH",
                        "management_protocol": "OPENFLOW",
                        "datapath_id": datapath_id,
                        "vendor": "OTHER",
                        "odl_mounted": True,
                        "odl_connection_status": "CONNECTED"
                    },
                    "update": {
                        "datapath_id": datapath_id,
                        "odl_mounted": True,
                        "odl_connection_status": "CONNECTED"
                    }
                }
            )
            device_id_map[node_id] = device.id
            stats["nodes_synced"] += 1
        else:
            # กรณี NETCONF อุปกรณ์ต้องมีอยู่แล้ว (เพราะเรา query มาจาก DB เพื่อดึง LLDP ยกเว้นฝั่งตรงข้ามที่อาจจะไม่เคยเพิ่มมาก่อน)
            # ป้องกันกรณี LLDP เห็นอุปกรณ์เพื่อนบ้านที่ยังไม่มีในระบบ (แต่ไม่สามารถติดต่อไปหาได้)
            existing = await prisma.devicenetwork.find_unique(where={"node_id": node_id})
            if existing:
                device_id_map[node_id] = existing.id
            else:
                # ลอง Upsert เป็น Dummy Router ไว้ก่อน เพื่อให้วาด Link ติด
                try:
                    device = await prisma.devicenetwork.upsert(
                        where={"node_id": node_id},
                        data={
                            "create": {
                                "node_id": node_id,
                                "device_name": node_id,
                                "serial_number": f"DUMMY-SN-{node_id}",
                                "mac_address": f"DUMMY-MAC-{node_id}",
                                "device_model": "Unknown Neighbor",
                                "type": "ROUTER",
                                "management_protocol": "OTHER",
                            },
                            "update": {}
                        }
                    )
                    device_id_map[node_id] = device.id
                except Exception:
                    pass
            
            stats["nodes_synced"] += 1

    # 2.2) Upsert Interfaces (Ports)
    # เราจำเป็นต้องสกัด source/target จาก Link เพื่อสร้าง Interface ให้ครบถ้วน
    interface_id_map: Dict[str, str] = {} # tp_id -> interface.id (UUID)
    
    unique_tps = set()
    for ln in raw_links:
        unique_tps.add(ln["source"])
        unique_tps.add(ln["target"])
        
    for tp_id in unique_tps:
        # สกัด node_id จาก tp_id
        # OpenFlow: "openflow:1:2" -> node_id = "openflow:1", port_number = 2
        # NETCONF (Cisco): "CSR1000vT:GigabitEthernet1" -> node_id = "CSR1000vT", port_name = "GigabitEthernet1"
        
        parts = tp_id.rsplit(':', 1)
        if len(parts) == 2:
            node_id, port_str = parts[0], parts[1]
        else:
            continue # Parse ผิดพลาด
            
        parent_uuid = device_id_map.get(node_id)
        if not parent_uuid:
            # Node ขาดไป ไม่สามารถอแดปเตอรพอร์ตให้ได้
            continue
            
        port_number = None
        if port_str.isdigit():
            port_number = int(port_str)
            
        # สร้างในตาราง Interface
        # หมายเหตุ: device_id ผูกกับ name เป็น Unique ใน schema (`@@unique([device_id, name])`)
        try:
            intf_record = await prisma.interface.find_first(
                where={"device_id": parent_uuid, "name": port_str}
            )
            
            if intf_record:
                intf_record = await prisma.interface.update(
                    where={"id": intf_record.id},
                    data={"tp_id": tp_id, "port_number": port_number}
                )
            else:
                intf_record = await prisma.interface.create(
                    data={
                        "device_id": parent_uuid,
                        "name": port_str,
                        "tp_id": tp_id,
                        "port_number": port_number,
                        "status": "UP"
                    }
                )
            
            interface_id_map[tp_id] = intf_record.id
            stats["interfaces_synced"] += 1
            
        except Exception as e:
            logger.error(f"Failed to upsert interface {tp_id}: {e}")

    # 2.3) Upsert Links
    active_link_ids = set()
    for ln in raw_links:
        src_uuid = interface_id_map.get(ln["source"])
        tgt_uuid = interface_id_map.get(ln["target"])
        link_id = ln["link_id"]
        
        if src_uuid and tgt_uuid:
            try:
                await prisma.link.upsert(
                    where={"link_id": link_id},
                    data={
                        "create": {
                            "link_id": link_id,
                            "source_interface_id": src_uuid,
                            "target_interface_id": tgt_uuid,
                        },
                        "update": {
                            "source_interface_id": src_uuid,
                            "target_interface_id": tgt_uuid,
                        }
                    }
                )
                active_link_ids.add(link_id)
                stats["links_synced"] += 1
            except Exception as e:
                logger.error(f"Failed to upsert link {link_id}: {e}")

    # =========================================================
    # 3. Clean up stale Links and Interfaces from Database
    # =========================================================
    try:
        # 3.1) Remove Links that no longer exist in ODL topology
        db_links = await prisma.link.find_many()
        stale_link_ids = []
        for db_link in db_links:
            # We don't delete manual links (assuming they start with "MANUAL:")
            if not db_link.link_id.startswith("MANUAL:") and db_link.link_id not in active_link_ids:
                stale_link_ids.append(db_link.id)
                
        if stale_link_ids:
            deleted_links = await prisma.link.delete_many(
                where={"id": {"in": stale_link_ids}}
            )
            stats["links_deleted"] = deleted_links.count
            logger.info(f"Deleted {deleted_links.count} stale links from topology.")
            
    except Exception as e:
        logger.error(f"Failed to clean up stale links: {e}")

    return stats
