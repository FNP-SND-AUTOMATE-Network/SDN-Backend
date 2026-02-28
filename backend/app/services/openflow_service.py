"""
OpenFlow Service
Service สำหรับจัดการ OpenFlow Flow Rules ผ่าน ODL RESTCONF API

Workflow:
1. รับ node_id + interface_ids จาก Frontend
2. Query DB เพื่อหา datapath_id และ port_number
3. สร้าง OpenFlow 1.3 YANG payload
4. ส่ง PUT/DELETE/GET ไปยัง ODL
"""
from typing import Dict, Any, Optional
from app.clients.odl_restconf_client import OdlRestconfClient
from app.schemas.request_spec import RequestSpec
from app.core.logging import logger
from app.database import get_prisma_client


class OpenFlowService:
    """
    Service สำหรับจัดการ OpenFlow Flow Rules

    ใช้ node_id (เช่น "openflow:1") ในการระบุ switch
    และ interface UUID ในการหา port_number สำหรับ match/action
    """

    # Base RESTCONF path สำหรับ OpenFlow inventory
    INVENTORY_BASE = "/opendaylight-inventory:nodes"

    def __init__(self):
        self.odl_client = OdlRestconfClient()

    # ============================================================
    # Public Methods
    # ============================================================

    async def add_flow(
        self,
        flow_id: str,
        node_id: str,
        inbound_interface_id: str,
        outbound_interface_id: str,
        priority: int = 500,
        table_id: int = 0,
    ) -> Dict[str, Any]:
        """
        เพิ่ม Flow Rule ลงใน OpenFlow Switch

        Steps:
            1. Query DeviceNetwork → validate node_id + get device info
            2. Query Interface → get inbound port_number
            3. Query Interface → get outbound port_number
            4. Construct OpenFlow 1.3 YANG payload
            5. PUT ไปยัง ODL RESTCONF
            6. Return result

        Args:
            flow_id: ชื่อกฎ (เช่น "ovs1-p1-to-p2")
            node_id: node_id ของ switch (เช่น "openflow:1")
            inbound_interface_id: UUID ของ Interface ขาเข้า
            outbound_interface_id: UUID ของ Interface ขาออก
            priority: ความสำคัญของกฎ (default: 500)
            table_id: Flow Table ID (default: 0)

        Returns:
            {"success": True/False, "message": "...", ...}
        """
        prisma = get_prisma_client()

        # ── Step 1: Validate device ──────────────────────────────
        device = await prisma.devicenetwork.find_first(
            where={"node_id": node_id}
        )
        if not device:
            raise ValueError(f"Device with node_id '{node_id}' not found in database")

        if device.management_protocol != "OPENFLOW":
            raise ValueError(
                f"Device '{node_id}' uses {device.management_protocol} protocol, "
                f"not OPENFLOW. Flow rules can only be applied to OpenFlow switches."
            )

        # ── Step 2: Query inbound port_number ────────────────────
        inbound_iface = await prisma.interface.find_unique(
            where={"id": inbound_interface_id}
        )
        if not inbound_iface:
            raise ValueError(f"Inbound interface '{inbound_interface_id}' not found")
        if inbound_iface.device_id != device.id:
            raise ValueError(
                f"Inbound interface does not belong to device '{node_id}'"
            )
        if inbound_iface.port_number is None:
            raise ValueError(
                f"Inbound interface '{inbound_iface.name}' has no port_number. "
                f"Sync OpenFlow topology first."
            )

        # ── Step 3: Query outbound port_number ───────────────────
        outbound_iface = await prisma.interface.find_unique(
            where={"id": outbound_interface_id}
        )
        if not outbound_iface:
            raise ValueError(f"Outbound interface '{outbound_interface_id}' not found")
        if outbound_iface.device_id != device.id:
            raise ValueError(
                f"Outbound interface does not belong to device '{node_id}'"
            )
        if outbound_iface.port_number is None:
            raise ValueError(
                f"Outbound interface '{outbound_iface.name}' has no port_number. "
                f"Sync OpenFlow topology first."
            )

        inbound_port = str(inbound_iface.port_number)
        outbound_port = str(outbound_iface.port_number)

        logger.info(
            f"Flow ADD: {flow_id} on {node_id} | "
            f"in={inbound_iface.name}(port {inbound_port}) → "
            f"out={outbound_iface.name}(port {outbound_port}) | "
            f"priority={priority}, table={table_id}"
        )

        # ── Step 4: Construct OpenFlow 1.3 YANG payload ──────────
        payload = self._build_flow_payload(
            flow_id=flow_id,
            table_id=table_id,
            priority=priority,
            inbound_port=inbound_port,
            outbound_port=outbound_port,
        )

        # ── Step 5: PUT to ODL ───────────────────────────────────
        path = (
            f"{self.INVENTORY_BASE}/node={node_id}"
            f"/flow-node-inventory:table={table_id}"
            f"/flow={flow_id}"
        )

        spec = RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        result = await self.odl_client.send(spec)

        # ── Step 6: Return success ───────────────────────────────
        return {
            "success": True,
            "message": f"Flow '{flow_id}' added successfully on {node_id}",
            "flow_id": flow_id,
            "node_id": node_id,
            "table_id": table_id,
            "inbound": {
                "interface_id": inbound_interface_id,
                "name": inbound_iface.name,
                "port_number": int(inbound_port),
            },
            "outbound": {
                "interface_id": outbound_interface_id,
                "name": outbound_iface.name,
                "port_number": int(outbound_port),
            },
            "priority": priority,
            "odl_response": result,
        }

    async def delete_flow(
        self,
        flow_id: str,
        node_id: str,
        table_id: int = 0,
    ) -> Dict[str, Any]:
        """
        ลบ Flow Rule ออกจาก OpenFlow Switch

        Args:
            flow_id: ชื่อกฎที่ต้องการลบ
            node_id: node_id ของ switch
            table_id: Flow Table ID (default: 0)

        Returns:
            {"success": True/False, "message": "..."}
        """
        prisma = get_prisma_client()

        # Validate device exists
        device = await prisma.devicenetwork.find_first(
            where={"node_id": node_id}
        )
        if not device:
            raise ValueError(f"Device with node_id '{node_id}' not found in database")

        logger.info(f"Flow DELETE: {flow_id} on {node_id}, table={table_id}")

        # DELETE from ODL
        path = (
            f"{self.INVENTORY_BASE}/node={node_id}"
            f"/flow-node-inventory:table={table_id}"
            f"/flow={flow_id}"
        )

        spec = RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"Accept": "application/json"},
        )

        result = await self.odl_client.send(spec)

        return {
            "success": True,
            "message": f"Flow '{flow_id}' deleted successfully from {node_id}",
            "flow_id": flow_id,
            "node_id": node_id,
            "table_id": table_id,
            "odl_response": result,
        }

    async def get_flows(
        self,
        node_id: str,
        table_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        ดึง Flow Rules ทั้งหมดจาก OpenFlow Switch

        Args:
            node_id: node_id ของ switch (เช่น "openflow:1")
            table_id: ถ้าระบุจะดูเฉพาะ table นั้น, ไม่ระบุดูทั้งหมด

        Returns:
            {"success": True, "flows": [...], ...}
        """
        prisma = get_prisma_client()

        # Validate device exists
        device = await prisma.devicenetwork.find_first(
            where={"node_id": node_id}
        )
        if not device:
            raise ValueError(f"Device with node_id '{node_id}' not found in database")

        logger.info(f"Flow GET: {node_id}, table={table_id or 'all'}")

        # Build path — specific table or whole node
        if table_id is not None:
            path = (
                f"{self.INVENTORY_BASE}/node={node_id}"
                f"/flow-node-inventory:table={table_id}"
            )
        else:
            path = f"{self.INVENTORY_BASE}/node={node_id}"

        spec = RequestSpec(
            method="GET",
            datastore="operational",  # operational เพื่อดู flow ที่ทำงานจริง
            path=path,
            payload=None,
            headers={"Accept": "application/json"},
        )

        result = await self.odl_client.send(spec)

        return {
            "success": True,
            "message": f"Flows retrieved from {node_id}",
            "node_id": node_id,
            "table_id": table_id,
            "flows": result,
        }

    # ============================================================
    # Private Methods
    # ============================================================

    @staticmethod
    def _build_flow_payload(
        flow_id: str,
        table_id: int,
        priority: int,
        inbound_port: str,
        outbound_port: str,
    ) -> Dict[str, Any]:
        """
        สร้าง OpenFlow 1.3 YANG model payload

        อ้างอิง: opendaylight-inventory / flow-node-inventory YANG model
        
        Structure:
        - flow[].match.in-port → inbound port
        - flow[].instructions.instruction[].apply-actions.action[].output-action → outbound port

        Args:
            flow_id: Flow rule identifier
            table_id: Table ID (usually 0)
            priority: Flow priority
            inbound_port: OpenFlow port number (inbound match)
            outbound_port: OpenFlow port number (outbound action)

        Returns:
            Complete flow-node-inventory:flow payload
        """
        return {
            "flow-node-inventory:flow": [
                {
                    "id": flow_id,
                    "table_id": table_id,
                    "priority": priority,
                    "match": {
                        "in-port": inbound_port,
                    },
                    "instructions": {
                        "instruction": [
                            {
                                "order": 0,
                                "apply-actions": {
                                    "action": [
                                        {
                                            "order": 0,
                                            "output-action": {
                                                "output-node-connector": outbound_port,
                                            },
                                        }
                                    ],
                                },
                            }
                        ],
                    },
                }
            ]
        }
