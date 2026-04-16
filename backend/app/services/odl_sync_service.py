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
import asyncio
from app.clients.odl_restconf_client import OdlRestconfClient
from app.schemas.request_spec import RequestSpec
from app.core.logging import logger
from app.database import get_prisma_client
from app.services.phpipam_service import PhpipamService


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
        self.phpipam_service = PhpipamService()
    
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
    
    async def sync_netconf_devices_from_odl(self) -> Dict[str, Any]:
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
            logger.info(f"[NETCONF-Sync] Starting NETCONF device sync — found {len(odl_nodes)} nodes in ODL topology-netconf")
            
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
                        # Sync phpIPAM tag to match new device status
                        if str(device.status) != new_status:
                            await self.phpipam_service.sync_device_status_to_ipam(device.id, new_status)
                        
                        logger.info(f"[NETCONF-Sync] {node_id} ({odl_node.get('host','?')}): connection={odl_node['connection_status']} → status={new_status}")
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
            
            # 4. Mark NETCONF devices as unmounted if not in ODL
            #    Skip OpenFlow devices — they are not in topology-netconf
            odl_node_ids = {n["node_id"] for n in odl_nodes}
            for device in db_devices:
                if device.node_id and device.node_id not in odl_node_ids:
                    # Skip OpenFlow devices (managed via topology_sync, not NETCONF)
                    if device.node_id.startswith("openflow:"):
                        continue
                    if device.management_protocol == "OPENFLOW":
                        continue
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
                        # Sync phpIPAM tag → Offline
                        await self.phpipam_service.sync_device_status_to_ipam(device.id, "OFFLINE")
                        logger.info(f"[NETCONF-Sync] {device.node_id}: not in ODL topology → status=OFFLINE (unmounted)")
                        result["synced"].append({
                            "node_id": device.node_id,
                            "device_id": device.id,
                            "device_name": device.device_name,
                            "status": "OFFLINE",
                            "connection_status": "not-mounted",
                            "note": "Unmounted from ODL"
                        })
            
            logger.info(f"[NETCONF-Sync] Completed: {len(result['synced'])} synced, {len(result['not_found'])} not found, {len(result['errors'])} errors")
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
            logger.info("[OF-Sync] Starting OpenFlow device sync from ODL inventory...")
            # 1. ดึง inventory จาก ODL
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
                error_str = str(e)
                # ไม่ว่า error อะไรก็ตาม → mark ทุก OF device เป็น OFFLINE
                reason = "409 data-missing" if ("409" in error_str and "data-missing" in error_str) else f"ODL error: {error_str[:100]}"
                logger.warning(f"[OF-Sync] ODL fetch failed ({reason}). Marking all OF devices OFFLINE.")
                db_of_devices = await prisma.devicenetwork.find_many(
                    where={"management_protocol": "OPENFLOW"}
                )
                for d in db_of_devices:
                    if d.status != "OFFLINE":
                        await prisma.devicenetwork.update(
                            where={"id": d.id},
                            data={
                                "status": "OFFLINE",
                                "odl_connection_status": "UNABLE_TO_CONNECT",
                                "last_synced_at": datetime.utcnow()
                            }
                        )
                        await self.phpipam_service.sync_device_status_to_ipam(d.id, "OFFLINE")
                        result["synced"].append({
                            "device_id": d.id,
                            "node_id": d.node_id,
                            "device_name": d.device_name,
                            "status": "OFFLINE",
                            "note": f"Marked OFFLINE ({reason})"
                        })
                logger.info(f"[OF-Sync] Marked {len(result['synced'])} OF devices OFFLINE")
                return result

            odl_active_ips = set()
            odl_active_node_ids = set()   # ALL OF nodes in inventory (for offline detection)
            odl_node_data = []            # Only nodes with IP (for data sync)

            # 2. Extract Data
            for node in nodes_list:
                node_id = node.get("id")
                ip_addr = node.get("flow-node-inventory:ip-address")
                
                # เก็บ node-connector ด้วย
                connectors = node.get("node-connector", [])
                
                if not node_id:
                    continue

                # Track ALL OF nodes as active (presence in inventory = connected)
                if node_id.startswith("openflow:"):
                    odl_active_node_ids.add(node_id)

                # Only sync data if we have IP
                if not ip_addr:
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
            
            # Map node_id or device_name to list of devices in DB
            db_lookup_map = {}
            for d in db_of_devices:
                key = d.node_id if d.node_id else d.device_name
                if key:
                    if key not in db_lookup_map:
                        db_lookup_map[key] = []
                    db_lookup_map[key].append(d)

            # odl_active_node_ids already built during extraction (step 2)
            logger.info(f"[OF-Sync] ODL active OF nodes: {odl_active_node_ids}, DB OF devices: {list(db_lookup_map.keys())}")

            # Mark devices offline that are in DB but not active in ODL
            for key, devices in db_lookup_map.items():
                if key not in odl_active_node_ids:
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
                            await self.phpipam_service.sync_device_status_to_ipam(d.id, "OFFLINE")

            # 4. Sync each ODL node to the DB
            for odl_nd in odl_node_data:
                odl_ip = odl_nd["ip"]
                odl_node_id = odl_nd["node_id"]
                connectors = odl_nd["connectors"]

                matched_devices = db_lookup_map.get(odl_node_id, [])

                if not matched_devices:
                    result["not_found"].append({"ip": odl_ip, "node_id": odl_node_id})
                    continue

                if len(matched_devices) > 1:
                    logger.warning(f"Duplicate device found in DB for OPENFLOW sync: {odl_node_id}")
                    # In real-world, might append to duplicate array, but let's just proceed with first

                device = matched_devices[0]

                # Check if this node_id is already used by another device (to prevent Unique Constraint Error)
                existing_node = await prisma.devicenetwork.find_unique(
                    where={"node_id": odl_node_id}
                )
                
                if existing_node and existing_node.id != device.id:
                    # Node might have been reassigned, clear the old one first
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

                # Update Device with new IP from ODL
                await prisma.devicenetwork.update(
                    where={"id": device.id},
                    data={
                        "node_id": odl_node_id,
                        "ip_address": odl_ip,
                        "datapath_id": extracted_dp_id,
                        "status": "ONLINE",
                        "odl_connection_status": "CONNECTED",
                        "last_synced_at": datetime.utcnow()
                    }
                )
                # Sync phpIPAM tag → Online
                if str(device.status) != "ONLINE":
                    await self.phpipam_service.sync_device_status_to_ipam(device.id, "ONLINE")

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

            logger.info(f"[OF-Sync] Completed: {len(result['synced'])} synced, {len(result['not_found'])} not found, {len(result['errors'])} errors")
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

    # ─── UNIFIED SYNC (NETCONF + OpenFlow) ────────────────────────
    async def sync_all_devices(self) -> Dict[str, Any]:
        """
        Sync ข้อมูล Device ทั้ง NETCONF และ OpenFlow จาก ODL ในครั้งเดียว
        ใช้ asyncio.gather() เพื่อรัน parallel ลด latency

        Returns:
            {
                "netconf": { "synced": [...], "not_found": [...], "errors": [...] },
                "openflow": { "synced": [...], "not_found": [...], "errors": [...] },
                "summary": { "total_synced": N, "total_not_found": N, "total_errors": N },
                "timestamp": "..."
            }
        """
        # Run both syncs in parallel
        netconf_result, openflow_result = await asyncio.gather(
            self.sync_netconf_devices_from_odl(),
            self.sync_openflow_devices_from_odl(),
            return_exceptions=True,
        )

        # Handle exceptions from gather
        if isinstance(netconf_result, Exception):
            logger.error(f"NETCONF sync failed in unified sync: {netconf_result}")
            netconf_result = {
                "synced": [], "not_found": [],
                "errors": [{"error": str(netconf_result)}],
                "timestamp": datetime.utcnow().isoformat(),
            }
        if isinstance(openflow_result, Exception):
            logger.error(f"OpenFlow sync failed in unified sync: {openflow_result}")
            openflow_result = {
                "synced": [], "not_found": [],
                "errors": [{"error": str(openflow_result)}],
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Build summary
        nc_synced = len(netconf_result.get("synced", []))
        of_synced = len(openflow_result.get("synced", []))
        nc_not_found = len(netconf_result.get("not_found", []))
        of_not_found = len(openflow_result.get("not_found", []))
        nc_errors = len(netconf_result.get("errors", []))
        of_errors = len(openflow_result.get("errors", []))

        logger.info(
            f"[UnifiedSync] NETCONF: {nc_synced} synced, {nc_not_found} not_found, {nc_errors} errors | "
            f"OpenFlow: {of_synced} synced, {of_not_found} not_found, {of_errors} errors"
        )

        return {
            "netconf": {
                "synced": netconf_result.get("synced", []),
                "not_found": netconf_result.get("not_found", []),
                "errors": netconf_result.get("errors", []),
            },
            "openflow": {
                "synced": openflow_result.get("synced", []),
                "not_found": openflow_result.get("not_found", []),
                "errors": openflow_result.get("errors", []),
            },
            "summary": {
                "total_synced": nc_synced + of_synced,
                "total_not_found": nc_not_found + of_not_found,
                "total_errors": nc_errors + of_errors,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ─── SINGLE DEVICE SYNC ───────────────────────────────────────
    async def sync_single_device_status(self, node_id: str) -> Dict[str, Any]:
        """
        Sync connection status ของ device ตัวเดียวจาก ODL → DB

        - NETCONF device: ดึงจาก topology-netconf
        - OpenFlow device: ดึงจาก opendaylight-inventory

        Returns:
            {
                "node_id": "...",
                "previous_status": "OFFLINE",
                "current_status": "ONLINE",
                "connection_status": "connected",
                "protocol": "NETCONF" | "OPENFLOW",
                "timestamp": "..."
            }
        """
        prisma = get_prisma_client()

        # 1. ค้นหา device ใน DB
        device = await prisma.devicenetwork.find_first(
            where={"node_id": node_id}
        )
        if not device:
            raise ValueError(f"Device with node_id '{node_id}' not found in database")

        previous_status = device.status
        protocol = device.management_protocol or "NETCONF"

        try:
            if protocol == "OPENFLOW" or node_id.startswith("openflow:"):
                # ─── OpenFlow: ดึงจาก inventory ─────────────
                connection_status, new_status = await self._check_openflow_status(node_id)
            else:
                # ─── NETCONF: ดึงจาก topology-netconf ────────
                connection_status, new_status = await self._check_netconf_status(node_id)

            db_connection_status = map_odl_status_to_enum(connection_status)

            # 2. อัปเดต DB
            await prisma.devicenetwork.update(
                where={"id": device.id},
                data={
                    "status": new_status,
                    "odl_connection_status": db_connection_status,
                    "odl_mounted": connection_status == "connected" or new_status == "ONLINE",
                    "last_synced_at": datetime.utcnow(),
                }
            )
            # Sync phpIPAM tag to match new device status
            if str(device.status) != new_status:
                await self.phpipam_service.sync_device_status_to_ipam(device.id, new_status)

            logger.info(
                f"[SingleSync] {node_id} ({protocol}): {previous_status} → {new_status} "
                f"(connection: {connection_status})"
            )

            return {
                "node_id": node_id,
                "device_name": device.device_name,
                "protocol": protocol,
                "previous_status": previous_status,
                "current_status": new_status,
                "connection_status": connection_status,
                "odl_connection_status": db_connection_status,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"[SingleSync] Failed to sync {node_id}: {e}")
            raise

    async def _check_netconf_status(self, node_id: str) -> tuple:
        """ตรวจสอบ NETCONF device status จาก ODL topology-netconf"""
        try:
            odl_nodes = await self.get_odl_mounted_nodes()
            odl_node = next((n for n in odl_nodes if n["node_id"] == node_id), None)

            if odl_node:
                conn = odl_node["connection_status"]
                new_status = "ONLINE" if conn == "connected" else "OFFLINE"
                return conn, new_status
            else:
                return "not-mounted", "OFFLINE"
        except Exception as e:
            logger.warning(f"[SingleSync] NETCONF check failed for {node_id}: {e}")
            return "unable-to-connect", "OFFLINE"

    async def _check_openflow_status(self, node_id: str) -> tuple:
        """ตรวจสอบ OpenFlow device status จาก ODL inventory"""
        try:
            spec = RequestSpec(
                method="GET",
                path=self.OPENFLOW_INVENTORY_PATH,
                datastore="operational",
                headers={"Accept": "application/yang-data+json"}
            )
            response = await self.odl_client.send(spec)
            nodes_list = response.get("opendaylight-inventory:nodes", {}).get("node", [])
            if not nodes_list:
                nodes_list = response.get("nodes", {}).get("node", [])

            # ค้นหา node ของเราใน inventory
            for node in nodes_list:
                if node.get("id") == node_id:
                    return "connected", "ONLINE"

            return "not-in-inventory", "OFFLINE"

        except Exception as e:
            error_str = str(e)
            if "409" in error_str and "data-missing" in error_str:
                return "not-in-inventory", "OFFLINE"
            logger.warning(f"[SingleSync] OpenFlow check failed for {node_id}: {e}")
            return "unable-to-connect", "OFFLINE"

