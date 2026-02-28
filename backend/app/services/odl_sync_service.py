"""
ODL Sync Service
Service สำหรับ Sync ข้อมูล Device จาก OpenDaylight มายัง Database

Flow:
1. ดึงรายการ mounted nodes จาก ODL topology-netconf
2. เปรียบเทียบกับ DeviceNetwork ใน DB
3. Update status และข้อมูลที่เกี่ยวข้อง
"""
from typing import Dict, List, Any, Optional
from datetime import datetime
from app.clients.odl_restconf_client import OdlRestconfClient
from app.schemas.request_spec import RequestSpec
from app.core.logging import logger
from app.database import get_prisma_client


# Map ODL connection status string to DB enum value
def map_odl_status_to_enum(odl_status: str) -> str:
    """
    Map ODL connection-status string to Prisma enum
    ODL returns: 'connected', 'connecting', 'unable-to-connect'
    DB enum: CONNECTED, CONNECTING, UNABLE_TO_CONNECT
    """
    mapping = {
        "connected": "CONNECTED",
        "connecting": "CONNECTING",
        "unable-to-connect": "UNABLE_TO_CONNECT",
        "not-mounted": "UNABLE_TO_CONNECT",
        "unknown": "UNABLE_TO_CONNECT",
    }
    return mapping.get(odl_status.lower() if odl_status else "unknown", "UNABLE_TO_CONNECT")


class OdlSyncService:
    """
    Service สำหรับ Sync ข้อมูลระหว่าง ODL และ Database
    """
    
    # ODL topology-netconf path
    NETCONF_TOPOLOGY_PATH = "/network-topology:network-topology/topology=topology-netconf"
    
    # ODL OPENFLOW Inventory path
    OPENFLOW_INVENTORY_PATH = "/opendaylight-inventory:nodes?content=nonconfig"
    
    def __init__(self):
        self.odl_client = OdlRestconfClient()
    
    async def get_odl_mounted_nodes(self) -> List[Dict[str, Any]]:
        """
        ดึงรายการ nodes ที่ mount อยู่ใน ODL topology-netconf
        
        Returns:
            List ของ node info: [{"node_id": "CSR1", "connection_status": "connected", ...}]
        """
        spec = RequestSpec(
            method="GET",
            path=self.NETCONF_TOPOLOGY_PATH,
            datastore="config",
            headers={"Accept": "application/yang-data+json"}
        )
        
        try:
            response = await self.odl_client.send(spec)
            
            # Parse response
            topology = response.get("network-topology:topology", [])
            if not topology:
                topology = response.get("topology", [])
            
            if not topology:
                return []
            
            nodes = []
            for topo in topology:
                node_list = topo.get("node", [])
                for node in node_list:
                    node_id = node.get("node-id", "")
                    
                    # Skip controller node
                    if node_id == "controller-config":
                        continue
                    
                    # Get connection status
                    netconf_node = node.get("netconf-node-topology:netconf-node", {})
                    connection_status = node.get(
                        "netconf-node-topology:connection-status",
                        netconf_node.get("connection-status", "unknown")
                    )
                    
                    # Get host/port info
                    host = node.get(
                        "netconf-node-topology:host",
                        netconf_node.get("host", "")
                    )
                    port = node.get(
                        "netconf-node-topology:port",
                        netconf_node.get("port", 830)
                    )
                    
                    # Get available capabilities
                    capabilities = node.get(
                        "netconf-node-topology:available-capabilities",
                        netconf_node.get("available-capabilities", {})
                    )
                    
                    nodes.append({
                        "node_id": node_id,
                        "connection_status": connection_status,
                        "host": host,
                        "port": port,
                        "capabilities": capabilities,
                        "raw": node  # Keep raw data for debugging
                    })
            
            return nodes
            
        except Exception as e:
            logger.error(f"Failed to get ODL mounted nodes: {e}")
            raise
    
    async def sync_devices_from_odl(self) -> Dict[str, Any]:
        """
        Sync ข้อมูล Device จาก ODL มา update ใน Database
        
        Flow:
        1. ดึง mounted nodes จาก ODL
        2. Update DeviceNetwork ที่มี node_id ตรงกัน
        3. Return สรุปผลการ sync
        
        Returns:
            {
                "synced": [...],      # Devices ที่ sync สำเร็จ
                "not_found": [...],   # ODL nodes ที่ไม่มีใน DB
                "errors": [...],      # Errors ที่เกิดขึ้น
                "timestamp": "..."
            }
        """
        prisma = get_prisma_client()
        
        result = {
            "synced": [],
            "not_found": [],
            "errors": [],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        try:
            # 1. Get ODL mounted nodes
            odl_nodes = await self.get_odl_mounted_nodes()
            logger.info(f"Found {len(odl_nodes)} nodes in ODL")
            
            # 2. Get all devices from DB that have node_id
            db_devices = await prisma.devicenetwork.find_many(
                where={"node_id": {"not": None}}
            )
            
            # Create lookup map: node_id -> device
            db_device_map = {d.node_id: d for d in db_devices if d.node_id}
            
            # 3. Process each ODL node
            for odl_node in odl_nodes:
                node_id = odl_node["node_id"]
                
                if node_id in db_device_map:
                    # Update existing device
                    try:
                        device = db_device_map[node_id]
                        
                        # Determine status based on connection
                        new_status = "ONLINE" if odl_node["connection_status"] == "connected" else "OFFLINE"
                        db_connection_status = map_odl_status_to_enum(odl_node["connection_status"])
                        
                        await prisma.devicenetwork.update(
                            where={"id": device.id},
                            data={
                                "odl_mounted": True,
                                "odl_connection_status": db_connection_status,
                                "status": new_status,
                                "last_synced_at": datetime.utcnow(),
                                # Update IP if available from ODL
                                "ip_address": odl_node.get("host") or device.ip_address,
                            }
                        )
                        
                        result["synced"].append({
                            "node_id": node_id,
                            "device_id": device.id,
                            "device_name": device.device_name,
                            "status": new_status,
                            "connection_status": odl_node["connection_status"]
                        })
                        
                    except Exception as e:
                        result["errors"].append({
                            "node_id": node_id,
                            "error": str(e)
                        })
                else:
                    # Node exists in ODL but not in DB
                    result["not_found"].append({
                        "node_id": node_id,
                        "host": odl_node.get("host"),
                        "connection_status": odl_node["connection_status"],
                        "message": "ODL node not found in database. Create DeviceNetwork with this node_id to sync."
                    })
            
            # 4. Mark devices as unmounted if not in ODL
            odl_node_ids = {n["node_id"] for n in odl_nodes}
            for device in db_devices:
                if device.node_id and device.node_id not in odl_node_ids:
                    if device.odl_mounted:  # Only update if was mounted
                        await prisma.devicenetwork.update(
                            where={"id": device.id},
                            data={
                                "odl_mounted": False,
                                "odl_connection_status": "UNABLE_TO_CONNECT",
                                "status": "OFFLINE",
                                "last_synced_at": datetime.utcnow()
                            }
                        )
                        result["synced"].append({
                            "node_id": device.node_id,
                            "device_id": device.id,
                            "device_name": device.device_name,
                            "status": "OFFLINE",
                            "connection_status": "not-mounted",
                            "note": "Unmounted from ODL"
                        })
            
            logger.info(f"Sync completed: {len(result['synced'])} synced, {len(result['not_found'])} not found")
            return result
            
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            result["errors"].append({"error": str(e)})
            return result
            
    async def sync_openflow_devices_from_odl(self) -> Dict[str, Any]:
        """
        Sync ข้อมูล Device ที่เป็น OpenFlow จาก ODL แบบอัตโนมัติ
        โดยจับคู่จาก IP Address
        
        Flow:
        1. ดึงข้อมูล nodes จาก /opendaylight-inventory:nodes?content=nonconfig
        2. วนลูปแล้วดึง node.id และ ip-address
        3. ค้นหาใน DB ด้วย ip_address และ management_protocol = 'OPENFLOW'
        4. อัปเดต node_id, status, last_synced_at
        5. ซิงค์ interface (node-connector -> Interface)
        """
        prisma = get_prisma_client()
        result = {
            "synced": [],
            "not_found": [],
            "errors": [],
            "duplicate_ips": [],
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            # 1. ปลดล็อค offline device ก่อน (สมมติว่าถ้าไม่มีใน ODL แล้วคือ OFFLINE)
            # เราจะเก็บ ip ไว้ล่ง ๆ แล้วค่อยไป update ONLINE ใน loop
            spec = RequestSpec(
                method="GET",
                path=self.OPENFLOW_INVENTORY_PATH,
                datastore="operational",
                headers={"Accept": "application/yang-data+json"}
            )
            try:
                response = await self.odl_client.send(spec)
                nodes_list = response.get("opendaylight-inventory:nodes", {}).get("node", [])
                if not nodes_list:
                    # ฟอลแบ็คสำหรับบางเวอร์ชัน ODL
                    nodes_list = response.get("nodes", {}).get("node", [])
            except Exception as e:
                logger.error(f"Failed to fetch OpenFlow inventory: {e}")
                result["errors"].append({"error": f"Failed to fetch from ODL: {str(e)}"})
                return result

            odl_active_ips = set()
            odl_node_data = []

            # 2. Extract Data
            for node in nodes_list:
                node_id = node.get("id")
                ip_addr = node.get("flow-node-inventory:ip-address")
                
                # เก็บ node-connector ด้วย
                connectors = node.get("node-connector", [])
                
                if not ip_addr or not node_id:
                    continue

                odl_active_ips.add(ip_addr)
                odl_node_data.append({
                    "node_id": node_id,
                    "ip": ip_addr,
                    "connectors": connectors
                })

            # 3. Get DB Devices with OPENFLOW
            db_of_devices = await prisma.devicenetwork.find_many(
                where={"management_protocol": "OPENFLOW"}
            )
            
            # Map ip_address to list of devices in DB (เพื่อตรวจจับ duplicate IP)
            ip_to_db_devices = {}
            for d in db_of_devices:
                if d.ip_address:
                    if d.ip_address not in ip_to_db_devices:
                        ip_to_db_devices[d.ip_address] = []
                    ip_to_db_devices[d.ip_address].append(d)

            # Mark devices offline that are in DB but not in ODL active IPs
            for ip, devices in ip_to_db_devices.items():
                if ip not in odl_active_ips:
                    for d in devices:
                        if d.status != "OFFLINE":
                            await prisma.devicenetwork.update(
                                where={"id": d.id},
                                data={
                                    "status": "OFFLINE",
                                    "odl_connection_status": "UNABLE_TO_CONNECT",
                                    "last_synced_at": datetime.utcnow()
                                }
                            )

            # 4. Sync each ODL node to the DB
            for odl_nd in odl_node_data:
                odl_ip = odl_nd["ip"]
                odl_node_id = odl_nd["node_id"]
                connectors = odl_nd["connectors"]

                matched_devices = ip_to_db_devices.get(odl_ip, [])

                if not matched_devices:
                    result["not_found"].append({"ip": odl_ip, "node_id": odl_node_id})
                    continue

                if len(matched_devices) > 1:
                    logger.warning(f"Duplicate IP found in DB for OPENFLOW sync: {odl_ip}")
                    result["duplicate_ips"].append(odl_ip)
                    # ข้าม หรือเลือกตัวแรกเพื่อความปลอดภัย? เลือกเตือนแล้วจัดการตัวแรกไปก่อน
                    # แต่ถ้าเข้มงวดคือ ข้าม
                    continue

                device = matched_devices[0]

                # Check if this node_id is already used by another device (to prevent Unique Constraint Error)
                existing_node = await prisma.devicenetwork.find_unique(
                    where={"node_id": odl_node_id}
                )
                
                if existing_node and existing_node.id != device.id:
                    # Node IP might have changed, clear the old one first
                    await prisma.devicenetwork.update(
                        where={"id": existing_node.id},
                        data={
                            "node_id": None,
                            "status": "OFFLINE",
                            "odl_connection_status": "UNABLE_TO_CONNECT"
                        }
                    )

                # Extract datapath_id from node_id (e.g. "openflow:1" -> "1")
                extracted_dp_id = None
                if odl_node_id.startswith("openflow:"):
                    extracted_dp_id = odl_node_id.replace("openflow:", "")

                # Update Device
                await prisma.devicenetwork.update(
                    where={"id": device.id},
                    data={
                        "node_id": odl_node_id,
                        "datapath_id": extracted_dp_id,
                        "status": "ONLINE",
                        "odl_connection_status": "CONNECTED",
                        "last_synced_at": datetime.utcnow()
                    }
                )

                # 5. Sync Interfaces
                for conn in connectors:
                    tp_id = conn.get("id")
                    port_num_str = conn.get("flow-node-inventory:port-number")
                    mac_addr = conn.get("flow-node-inventory:hardware-address")
                    name = conn.get("flow-node-inventory:name", tp_id)
                    
                    if not tp_id:
                        continue
                        
                    # Parse port number
                    port_num = None
                    if port_num_str:
                        try:
                            # บางทีเป็น string "LOCAL", ข้ามถ้า cast int ไม่ได้
                            if str(port_num_str).isdigit():
                                port_num = int(port_num_str)
                        except:
                            pass

                    # Upsert Interface
                    # tp_id is unique, so we should first try to find by tp_id
                    existing_iface = await prisma.interface.find_unique(
                        where={"tp_id": tp_id}
                    )
                    
                    if not existing_iface:
                        # Fallback to device_id and name if tp_id wasn't set yet
                        existing_iface = await prisma.interface.find_unique(
                            where={"device_id_name": {"device_id": device.id, "name": name}}
                        )

                    params = {
                        "name": name,
                        "label": name,
                        "tp_id": tp_id,
                        "port_number": port_num,
                        "mac_address": mac_addr,
                        "status": "UP", # สมมติว่าพอร์ตมาด้วยคือ UP
                        "device_id": device.id # ย้ายมาผูกกับ device ปัจจุบันเสมอเผื่อเปลี่ยน
                    }

                    if existing_iface:
                        # อัปเดตข้อมูลและย้าย device_id (ถ้าเปลี่ยน)
                        await prisma.interface.update(
                            where={"id": existing_iface.id},
                            data=params
                        )
                    else:
                        await prisma.interface.create(
                            data={
                                **params,
                                "type": "PHYSICAL"
                            }
                        )

                result["synced"].append({
                    "device_id": device.id,
                    "ip_address": odl_ip,
                    "node_id": odl_node_id,
                    "interfaces_synced": len(connectors)
                })

            return result

        except Exception as e:
            logger.error(f"Sync OpenFlow failed: {e}")
            result["errors"].append({"error": str(e)})
            return result
    
    async def auto_create_from_odl(self, node_id: str, vendor: str = "cisco") -> Optional[Dict[str, Any]]:
        """
        สร้าง DeviceNetwork อัตโนมัติจาก ODL node
        
        Args:
            node_id: ODL node-id
            vendor: Vendor ของ device (cisco, huawei, etc.)
        
        Returns:
            Created device info หรือ None ถ้าไม่สำเร็จ
        """
        prisma = get_prisma_client()
        
        try:
            # Get ODL nodes
            odl_nodes = await self.get_odl_mounted_nodes()
            odl_node = next((n for n in odl_nodes if n["node_id"] == node_id), None)
            
            if not odl_node:
                raise ValueError(f"Node {node_id} not found in ODL")
            
            # Check if already exists
            existing = await prisma.devicenetwork.find_first(
                where={"node_id": node_id}
            )
            if existing:
                raise ValueError(f"Device with node_id {node_id} already exists")
            
            # Determine vendor enum
            vendor_map = {
                "cisco": "CISCO",
                "huawei": "HUAWEI",
                "juniper": "JUNIPER",
                "arista": "ARISTA"
            }
            vendor_enum = vendor_map.get(vendor.lower(), "OTHER")
            
            # Create device
            db_connection_status = map_odl_status_to_enum(odl_node["connection_status"])
            device = await prisma.devicenetwork.create(
                data={
                    "serial_number": f"ODL-{node_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                    "device_name": node_id,
                    "device_model": "Auto-created from ODL",
                    "type": "ROUTER",
                    "status": "ONLINE" if odl_node["connection_status"] == "connected" else "OFFLINE",
                    "ip_address": odl_node.get("host"),
                    "mac_address": f"00:00:00:{node_id[:2]}:{node_id[-2:] if len(node_id) > 2 else '00'}:01".upper(),
                    "description": f"Auto-created from ODL mount. Node: {node_id}",
                    "node_id": node_id,
                    "vendor": vendor_enum,
                    "odl_mounted": True,
                    "odl_connection_status": db_connection_status,
                    "last_synced_at": datetime.utcnow()
                }
            )
            
            return {
                "id": device.id,
                "node_id": device.node_id,
                "device_name": device.device_name,
                "vendor": device.vendor,
                "status": device.status,
                "message": "Device created successfully from ODL"
            }
            
        except Exception as e:
            logger.error(f"Failed to auto-create device from ODL: {e}")
            raise
    
    async def detect_vendor_from_capabilities(self, capabilities: Dict) -> str:
        """
        ตรวจจับ vendor จาก NETCONF capabilities
        
        Args:
            capabilities: Available capabilities from ODL
        
        Returns:
            Detected vendor: "cisco", "huawei", "juniper", etc.
        """
        cap_list = capabilities.get("available-capability", [])
        cap_str = str(cap_list).lower()
        
        if "cisco" in cap_str or "tailf" in cap_str:
            return "cisco"
        elif "huawei" in cap_str:
            return "huawei"
        elif "juniper" in cap_str:
            return "juniper"
        elif "arista" in cap_str:
            return "arista"
        else:
            return "other"
