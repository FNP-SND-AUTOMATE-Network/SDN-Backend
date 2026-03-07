"""
OpenFlow Service — with FlowRule DB Tracking
Service สำหรับจัดการ OpenFlow Flow Rules ผ่าน ODL RESTCONF API

Workflow:
1. รับ node_id + params จาก Frontend
2. Validate device + interface (query DB)
3. INSERT FlowRule → status=PENDING
4. PUT payload → ODL RESTCONF
5. สำเร็จ → status=ACTIVE / ล้มเหลว → status=FAILED
"""
from typing import Dict, Any, Optional, List
from app.clients.odl_restconf_client import OdlRestconfClient
from app.schemas.request_spec import RequestSpec
from app.core.logging import logger
from app.database import get_prisma_client
import json


# FlowStatus string constants (match Prisma enum)
class FlowStatus:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    DELETED = "DELETED"


class OpenFlowService:
    """Service สำหรับจัดการ OpenFlow Flow Rules + DB Tracking"""

    INVENTORY_BASE = "/opendaylight-inventory:nodes"

    def __init__(self):
        self.odl_client = OdlRestconfClient()

    # ============================================================
    # Shared Helpers
    # ============================================================

    async def _validate_device(self, node_id: str):
        """Validate ว่า device มีอยู่ใน DB และเป็น OPENFLOW switch"""
        prisma = get_prisma_client()
        device = await prisma.devicenetwork.find_first(
            where={"node_id": node_id}
        )
        if not device:
            raise ValueError(f"Device with node_id '{node_id}' not found in database")
        if device.management_protocol != "OPENFLOW":
            raise ValueError(
                f"Device '{node_id}' uses {device.management_protocol}, not OPENFLOW."
            )
        return device

    async def _validate_interface(self, interface_id: str, device, label: str = "Interface"):
        """Validate interface: exists, belongs to device, has port_number"""
        prisma = get_prisma_client()
        iface = await prisma.interface.find_unique(where={"id": interface_id})
        if not iface:
            raise ValueError(f"{label} interface '{interface_id}' not found")
        if iface.device_id != device.id:
            raise ValueError(f"{label} interface does not belong to device '{device.node_id}'")
        if iface.port_number is None:
            raise ValueError(
                f"{label} interface '{iface.name}' has no port_number. Sync topology first."
            )
        return iface

    async def _push_flow_to_odl(
        self, flow_id: str, node_id: str, table_id: int, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """PUT flow payload ไปยัง ODL RESTCONF"""
        path = (
            f"{self.INVENTORY_BASE}/node={node_id}"
            f"/flow-node-inventory:table={table_id}"
            f"/flow={flow_id}"
        )
        spec = RequestSpec(
            method="PUT", datastore="config", path=path, payload=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        return await self.odl_client.send(spec)

    async def _save_flow_to_db(
        self,
        flow_id: str,
        node_id: str,
        table_id: int,
        flow_type: str,
        priority: int,
        bidirectional: bool = False,
        pair_flow_id: Optional[str] = None,
        direction: Optional[str] = None,
        match_details: Optional[Dict] = None,
    ):
        """INSERT FlowRule → status=PENDING"""
        prisma = get_prisma_client()
        existing = await prisma.flowrule.find_first(
            where={
                "node_id": node_id,
                "flow_id": flow_id,
                "table_id": table_id,
            }
        )
        
        data = {
            "flow_type": flow_type,
            "priority": priority,
            "bidirectional": bidirectional,
            "pair_flow_id": pair_flow_id,
            "direction": direction,
            "match_details": json.dumps(match_details) if match_details else "{}",
            "status": FlowStatus.PENDING,
        }
        
        if existing:
            return await prisma.flowrule.update(
                where={"id": existing.id},
                data=data,
            )
        else:
            return await prisma.flowrule.create(
                data={
                    "flow_id": flow_id,
                    "node_id": node_id,
                    "table_id": table_id,
                    **data
                }
            )

    async def _update_flow_status(self, db_id: str, status: FlowStatus):
        """Update FlowRule status"""
        prisma = get_prisma_client()
        await prisma.flowrule.update(
            where={"id": db_id},
            data={"status": status},
        )

    async def _push_and_track(
        self,
        db_record,
        flow_id: str,
        node_id: str,
        table_id: int,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """PUT → ODL + update DB status (ACTIVE or FAILED)"""
        try:
            result = await self._push_flow_to_odl(flow_id, node_id, table_id, payload)
            await self._update_flow_status(db_record.id, FlowStatus.ACTIVE)
            return result
        except Exception:
            await self._update_flow_status(db_record.id, FlowStatus.FAILED)
            raise

    # ============================================================
    # 1. ARP Flood
    # ============================================================

    async def add_arp_flood_flow(
        self, flow_id: str, node_id: str,
        priority: int = 400, table_id: int = 0,
    ) -> Dict[str, Any]:
        """ARP Flood — Match ethernet-type=ARP → FLOOD"""
        await self._validate_device(node_id)
        logger.info(f"Flow ADD [arp-flood]: {flow_id} on {node_id}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "arp_flood", priority,
        )

        payload = self._build_arp_flood_payload(flow_id, table_id, priority)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "arp_flood",
            "message": f"ARP Flood '{flow_id}' added on {node_id}",
            "flow_id": flow_id, "node_id": node_id,
            "table_id": table_id, "priority": priority,
            "flow_rule_id": db_record.id,
            "odl_response": result,
        }

    # ============================================================
    # 2. Base Connectivity (bidirectional)
    # ============================================================

    async def add_flow(
        self, flow_id: str, node_id: str,
        inbound_interface_id: str, outbound_interface_id: str,
        priority: int = 500, table_id: int = 0,
        bidirectional: bool = True,
    ) -> Dict[str, Any]:
        """Base Connectivity — L1 Forwarding (bidirectional by default)"""
        device = await self._validate_device(node_id)
        inbound_iface = await self._validate_interface(inbound_interface_id, device, "Inbound")
        outbound_iface = await self._validate_interface(outbound_interface_id, device, "Outbound")

        in_port = str(inbound_iface.port_number)
        out_port = str(outbound_iface.port_number)
        flows_created: List[Dict[str, Any]] = []

        if bidirectional:
            fwd_id = f"{flow_id}-forward"
            rev_id = f"{flow_id}-reverse"

            # DB: save both as PENDING
            fwd_db = await self._save_flow_to_db(
                fwd_id, node_id, table_id, "base_connectivity", priority,
                bidirectional=True, pair_flow_id=rev_id, direction="forward",
                match_details={"in_port": int(in_port), "out_port": int(out_port)},
            )
            rev_db = await self._save_flow_to_db(
                rev_id, node_id, table_id, "base_connectivity", priority,
                bidirectional=True, pair_flow_id=fwd_id, direction="reverse",
                match_details={"in_port": int(out_port), "out_port": int(in_port)},
            )

            # ODL: push forward
            logger.info(f"Flow ADD [wiring-fwd]: {fwd_id} on {node_id} | {in_port}→{out_port}")
            fwd_payload = self._build_wiring_payload(fwd_id, table_id, priority, in_port, out_port)
            fwd_result = await self._push_and_track(fwd_db, fwd_id, node_id, table_id, fwd_payload)
            flows_created.append({
                "flow_id": fwd_id, "direction": "forward",
                "in_port": int(in_port), "out_port": int(out_port),
                "flow_rule_id": fwd_db.id, "odl_response": fwd_result,
            })

            # ODL: push reverse
            logger.info(f"Flow ADD [wiring-rev]: {rev_id} on {node_id} | {out_port}→{in_port}")
            rev_payload = self._build_wiring_payload(rev_id, table_id, priority, out_port, in_port)
            rev_result = await self._push_and_track(rev_db, rev_id, node_id, table_id, rev_payload)
            flows_created.append({
                "flow_id": rev_id, "direction": "reverse",
                "in_port": int(out_port), "out_port": int(in_port),
                "flow_rule_id": rev_db.id, "odl_response": rev_result,
            })
        else:
            logger.info(f"Flow ADD [wiring]: {flow_id} on {node_id} | {in_port}→{out_port}")
            db_record = await self._save_flow_to_db(
                flow_id, node_id, table_id, "base_connectivity", priority,
                match_details={"in_port": int(in_port), "out_port": int(out_port)},
            )
            payload = self._build_wiring_payload(flow_id, table_id, priority, in_port, out_port)
            result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)
            flows_created.append({
                "flow_id": flow_id, "direction": "forward",
                "in_port": int(in_port), "out_port": int(out_port),
                "flow_rule_id": db_record.id, "odl_response": result,
            })

        direction_text = "bidirectional" if bidirectional else "unidirectional"
        return {
            "success": True, "flow_type": "base_connectivity",
            "message": f"Base connectivity '{flow_id}' on {node_id} ({direction_text}, {len(flows_created)} flow(s))",
            "node_id": node_id, "table_id": table_id, "priority": priority,
            "bidirectional": bidirectional,
            "flows_created": flows_created,
        }

    # ============================================================
    # 3. Traffic Steering L4 (bidirectional)
    # ============================================================

    async def add_traffic_steer_flow(
        self, flow_id: str, node_id: str,
        inbound_interface_id: str, outbound_interface_id: str,
        dst_port: int, protocol: str = "tcp", priority: int = 600,
        table_id: int = 0, bidirectional: bool = True,
    ) -> Dict[str, Any]:
        """Traffic Steering — L4 Redirect (TCP/UDP, bidirectional by default)"""
        proto = protocol.lower()
        device = await self._validate_device(node_id)
        inbound_iface = await self._validate_interface(inbound_interface_id, device, "Inbound")
        outbound_iface = await self._validate_interface(outbound_interface_id, device, "Outbound")

        in_port = str(inbound_iface.port_number)
        out_port = str(outbound_iface.port_number)
        flows_created: List[Dict[str, Any]] = []

        if bidirectional:
            fwd_id = f"{flow_id}-forward"
            rev_id = f"{flow_id}-reverse"

            fwd_db = await self._save_flow_to_db(
                fwd_id, node_id, table_id, "traffic_steering", priority,
                bidirectional=True, pair_flow_id=rev_id, direction="forward",
                match_details={"in_port": int(in_port), "out_port": int(out_port), "dst_port": dst_port, "protocol": proto},
            )
            rev_db = await self._save_flow_to_db(
                rev_id, node_id, table_id, "traffic_steering", priority,
                bidirectional=True, pair_flow_id=fwd_id, direction="reverse",
                match_details={"in_port": int(out_port), "out_port": int(in_port), "dst_port": dst_port, "protocol": proto},
            )

            logger.info(f"Flow ADD [steer-fwd]: {fwd_id} on {node_id} | {proto.upper()}:{dst_port}")
            fwd_payload = self._build_steering_payload(fwd_id, table_id, priority, in_port, out_port, dst_port, proto)
            fwd_result = await self._push_and_track(fwd_db, fwd_id, node_id, table_id, fwd_payload)
            flows_created.append({
                "flow_id": fwd_id, "direction": "forward", "dst_port": dst_port, "protocol": proto,
                "flow_rule_id": fwd_db.id, "odl_response": fwd_result,
            })

            logger.info(f"Flow ADD [steer-rev]: {rev_id} on {node_id} | {proto.upper()}:{dst_port}")
            rev_payload = self._build_steering_payload(rev_id, table_id, priority, out_port, in_port, dst_port, proto)
            rev_result = await self._push_and_track(rev_db, rev_id, node_id, table_id, rev_payload)
            flows_created.append({
                "flow_id": rev_id, "direction": "reverse", "dst_port": dst_port, "protocol": proto,
                "flow_rule_id": rev_db.id, "odl_response": rev_result,
            })
        else:
            logger.info(f"Flow ADD [steer]: {flow_id} on {node_id} | {proto.upper()}:{dst_port}")
            db_record = await self._save_flow_to_db(
                flow_id, node_id, table_id, "traffic_steering", priority,
                match_details={"in_port": int(in_port), "out_port": int(out_port), "dst_port": dst_port, "protocol": proto},
            )
            payload = self._build_steering_payload(flow_id, table_id, priority, in_port, out_port, dst_port, proto)
            result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)
            flows_created.append({
                "flow_id": flow_id, "direction": "forward", "dst_port": dst_port, "protocol": proto,
                "flow_rule_id": db_record.id, "odl_response": result,
            })

        direction_text = "bidirectional" if bidirectional else "unidirectional"
        return {
            "success": True, "flow_type": "traffic_steering",
            "message": f"Traffic steering '{flow_id}' on {node_id} — {proto.upper()}:{dst_port} ({direction_text})",
            "node_id": node_id, "dst_port": dst_port, "protocol": proto, "bidirectional": bidirectional,
            "flows_created": flows_created,
        }

    # ============================================================
    # 4a. ACL: L2 MAC Drop
    # ============================================================

    async def add_acl_mac_drop(
        self, flow_id: str, node_id: str, src_mac: str,
        priority: int = 1100, table_id: int = 0,
    ) -> Dict[str, Any]:
        """L2 ACL — Drop ทุก traffic จาก source MAC"""
        await self._validate_device(node_id)
        logger.info(f"Flow ADD [acl-mac-drop]: {flow_id} on {node_id} | src={src_mac}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "acl_mac_drop", priority,
            match_details={"src_mac": src_mac},
        )
        payload = self._build_acl_mac_drop_payload(flow_id, table_id, priority, src_mac)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "acl_mac_drop",
            "message": f"ACL MAC drop '{flow_id}' on {node_id}: {src_mac} → DROP",
            "flow_id": flow_id, "node_id": node_id, "src_mac": src_mac,
            "flow_rule_id": db_record.id, "odl_response": result,
        }

    # ============================================================
    # 4b. ACL: L3 IP Blacklist
    # ============================================================

    async def add_acl_ip_blacklist(
        self, flow_id: str, node_id: str, src_ip: str, dst_ip: str,
        priority: int = 1100, table_id: int = 0,
    ) -> Dict[str, Any]:
        """L3 ACL — Drop traffic จาก src_ip ไปหา dst_ip"""
        await self._validate_device(node_id)
        logger.info(f"Flow ADD [acl-ip-blacklist]: {flow_id} on {node_id} | {src_ip}→{dst_ip}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "acl_ip_blacklist", priority,
            match_details={"src_ip": src_ip, "dst_ip": dst_ip},
        )
        payload = self._build_acl_ip_blacklist_payload(flow_id, table_id, priority, src_ip, dst_ip)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "acl_ip_blacklist",
            "message": f"ACL IP blacklist '{flow_id}' on {node_id}: {src_ip}→{dst_ip} → DROP",
            "flow_id": flow_id, "node_id": node_id, "src_ip": src_ip, "dst_ip": dst_ip,
            "flow_rule_id": db_record.id, "odl_response": result,
        }

    # ============================================================
    # 4c. ACL: L4 Port Drop
    # ============================================================

    async def add_acl_port_drop(
        self, flow_id: str, node_id: str, dst_port: int,
        protocol: str = "tcp", priority: int = 1200, table_id: int = 0,
    ) -> Dict[str, Any]:
        """L4 ACL — Drop traffic ที่ไปหา destination port (TCP/UDP)"""
        proto = protocol.lower()
        await self._validate_device(node_id)
        logger.info(f"Flow ADD [acl-port-drop]: {flow_id} on {node_id} | {proto.upper()}:{dst_port}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "acl_port_drop", priority,
            match_details={"dst_port": dst_port, "protocol": proto},
        )
        payload = self._build_acl_port_drop_payload(flow_id, table_id, priority, dst_port, proto)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "acl_port_drop",
            "message": f"ACL port drop '{flow_id}' on {node_id}: {proto.upper()}:{dst_port} → DROP",
            "flow_id": flow_id, "node_id": node_id, "dst_port": dst_port, "protocol": proto,
            "flow_rule_id": db_record.id, "odl_response": result,
        }

    # ============================================================
    # 4d. ACL: Whitelist
    # ============================================================

    async def add_acl_whitelist(
        self, flow_id: str, node_id: str, dst_port: int,
        protocol: str = "tcp", priority: int = 1000, table_id: int = 0,
    ) -> Dict[str, Any]:
        """Whitelist — อนุญาตเฉพาะ port ที่กำหนด (TCP/UDP, output NORMAL)"""
        proto = protocol.lower()
        await self._validate_device(node_id)
        logger.info(f"Flow ADD [acl-whitelist]: {flow_id} on {node_id} | {proto.upper()}:{dst_port}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "acl_whitelist", priority,
            match_details={"dst_port": dst_port, "protocol": proto},
        )
        payload = self._build_acl_whitelist_payload(flow_id, table_id, priority, dst_port, proto)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "acl_whitelist",
            "message": f"ACL whitelist '{flow_id}' on {node_id}: {proto.upper()}:{dst_port} → PERMIT",
            "flow_id": flow_id, "node_id": node_id, "dst_port": dst_port, "protocol": proto,
            "flow_rule_id": db_record.id, "odl_response": result,
        }

    # ============================================================
    # 5. L2 MAC Steering
    # ============================================================

    async def add_mac_steer_flow(
        self, flow_id: str, node_id: str,
        src_mac: str, outbound_interface_id: str,
        priority: int = 960, table_id: int = 0,
    ) -> Dict[str, Any]:
        """L2 MAC Steering — Match ethernet-source → output"""
        device = await self._validate_device(node_id)
        outbound_iface = await self._validate_interface(outbound_interface_id, device, "Outbound")
        out_port = str(outbound_iface.port_number)

        logger.info(f"Flow ADD [steer-mac]: {flow_id} on {node_id} | {src_mac}→port {out_port}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "mac_steering", priority,
            match_details={"src_mac": src_mac, "out_port": int(out_port)},
        )
        payload = self._build_mac_steering_payload(flow_id, table_id, priority, src_mac, out_port)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "mac_steering",
            "message": f"MAC steering '{flow_id}' on {node_id}: {src_mac}→port {out_port}",
            "flow_id": flow_id, "node_id": node_id, "src_mac": src_mac,
            "outbound": {"interface_id": outbound_interface_id, "name": outbound_iface.name, "port_number": int(out_port)},
            "flow_rule_id": db_record.id, "odl_response": result,
        }

    # ============================================================
    # 6. L3 IP Steering
    # ============================================================

    async def add_ip_steer_flow(
        self, flow_id: str, node_id: str,
        dst_ip: str, outbound_interface_id: str,
        priority: int = 960, table_id: int = 0,
    ) -> Dict[str, Any]:
        """L3 IP Steering — Match IPv4 + ipv4-destination → output"""
        device = await self._validate_device(node_id)
        outbound_iface = await self._validate_interface(outbound_interface_id, device, "Outbound")
        out_port = str(outbound_iface.port_number)

        logger.info(f"Flow ADD [steer-ip]: {flow_id} on {node_id} | {dst_ip}→port {out_port}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "ip_steering", priority,
            match_details={"dst_ip": dst_ip, "out_port": int(out_port)},
        )
        payload = self._build_ip_steering_payload(flow_id, table_id, priority, dst_ip, out_port)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "ip_steering",
            "message": f"IP steering '{flow_id}' on {node_id}: {dst_ip}→port {out_port}",
            "flow_id": flow_id, "node_id": node_id, "dst_ip": dst_ip,
            "outbound": {"interface_id": outbound_interface_id, "name": outbound_iface.name, "port_number": int(out_port)},
            "flow_rule_id": db_record.id, "odl_response": result,
        }

    # ============================================================
    # 7. Default Gateway Forwarding
    # ============================================================

    async def add_default_gateway_flow(
        self, flow_id: str, node_id: str, outbound_interface_id: str,
        priority: int = 100, table_id: int = 0,
    ) -> Dict[str, Any]:
        """Default Gateway — ทราฟฟิกที่ไม่ตรงกับกฎใดๆ ให้ส่งออกไปที่ Gateway"""
        device = await self._validate_device(node_id)
        outbound_iface = await self._validate_interface(outbound_interface_id, device, "Outbound")
        out_port = str(outbound_iface.port_number)

        logger.info(f"Flow ADD [default-gw]: {flow_id} on {node_id} | →port {out_port}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "default_gateway", priority,
            match_details={"out_port": int(out_port)},
        )
        payload = self._build_default_gw_payload(flow_id, table_id, priority, out_port)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "default_gateway",
            "message": f"Default Gateway '{flow_id}' on {node_id} → port {out_port}",
            "flow_id": flow_id, "node_id": node_id,
            "outbound": {"interface_id": outbound_interface_id, "name": outbound_iface.name, "port_number": int(out_port)},
            "flow_rule_id": db_record.id, "odl_response": result,
        }

    # ============================================================
    # 8. L3 Subnet Steering
    # ============================================================

    async def add_subnet_steer_flow(
        self, flow_id: str, node_id: str,
        src_ip_subnet: str, outbound_interface_id: str,
        priority: int = 960, table_id: int = 0,
    ) -> Dict[str, Any]:
        """L3 Subnet Steering — redirect traffic ตามวง Source IP"""
        device = await self._validate_device(node_id)
        outbound_iface = await self._validate_interface(outbound_interface_id, device, "Outbound")
        out_port = str(outbound_iface.port_number)

        logger.info(f"Flow ADD [steer-subnet]: {flow_id} on {node_id} | {src_ip_subnet}→port {out_port}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "subnet_steering", priority,
            match_details={"src_ip_subnet": src_ip_subnet, "out_port": int(out_port)},
        )
        payload = self._build_subnet_steering_payload(flow_id, table_id, priority, src_ip_subnet, out_port)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "subnet_steering",
            "message": f"Subnet steering '{flow_id}' on {node_id}: {src_ip_subnet}→port {out_port}",
            "flow_id": flow_id, "node_id": node_id, "src_ip_subnet": src_ip_subnet,
            "outbound": {"interface_id": outbound_interface_id, "name": outbound_iface.name, "port_number": int(out_port)},
            "flow_rule_id": db_record.id, "odl_response": result,
        }

    # ============================================================
    # 9. L3 ICMP Control
    # ============================================================

    async def add_icmp_control(
        self, flow_id: str, node_id: str, action: str = "DROP",
        priority: int = 1100, table_id: int = 0,
    ) -> Dict[str, Any]:
        """L3 ICMP Control — บล็อกหรืออนุญาตการ Ping"""
        await self._validate_device(node_id)
        action_upper = action.upper()
        
        logger.info(f"Flow ADD [icmp-control]: {flow_id} on {node_id} | action={action_upper}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "icmp_control", priority,
            match_details={"action": action_upper},
        )
        payload = self._build_icmp_payload(flow_id, table_id, priority, action_upper)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "icmp_control",
            "message": f"ICMP Control '{flow_id}' on {node_id} (Action: {action_upper})",
            "flow_id": flow_id, "node_id": node_id, "action": action_upper,
            "flow_rule_id": db_record.id, "odl_response": result,
        }

    # ============================================================
    # Smart Delete (bidirectional auto-pair)
    # ============================================================

    async def delete_flow(
        self, flow_id: str, node_id: str, table_id: int = 0,
    ) -> Dict[str, Any]:
        """ลบ Flow Rule — ถ้าเป็น bidirectional จะลบคู่ด้วยอัตโนมัติ"""
        await self._validate_device(node_id)
        prisma = get_prisma_client()

        # ① Query DB เพื่อหา flow + คู่
        db_flow = await prisma.flowrule.find_first(
            where={
                "node_id": node_id,
                "flow_id": flow_id,
                "table_id": table_id,
                "status": FlowStatus.ACTIVE,
            }
        )

        flows_to_delete = [flow_id]
        db_ids_to_update = []

        if db_flow:
            db_ids_to_update.append(db_flow.id)
            # ② ถ้ามี pair → ลบคู่ด้วย
            if db_flow.pair_flow_id:
                flows_to_delete.append(db_flow.pair_flow_id)
                pair_record = await prisma.flowrule.find_first(
                    where={
                        "node_id": node_id,
                        "flow_id": db_flow.pair_flow_id,
                        "table_id": table_id,
                        "status": FlowStatus.ACTIVE,
                    }
                )
                if pair_record:
                    db_ids_to_update.append(pair_record.id)
                logger.info(
                    f"Flow DELETE [bidirectional]: {flow_id} + {db_flow.pair_flow_id} on {node_id}"
                )
        else:
            logger.info(f"Flow DELETE: {flow_id} on {node_id} (no DB record)")

        # ③ DELETE จาก ODL ทั้งหมด
        odl_results = []
        for fid in flows_to_delete:
            path = (
                f"{self.INVENTORY_BASE}/node={node_id}"
                f"/flow-node-inventory:table={table_id}"
                f"/flow={fid}"
            )
            spec = RequestSpec(
                method="DELETE", datastore="config", path=path,
                payload=None, headers={"Accept": "application/json"},
            )
            result = await self.odl_client.send(spec)
            odl_results.append({"flow_id": fid, "odl_response": result})

        # ④ UPDATE DB → DELETED
        for db_id in db_ids_to_update:
            await self._update_flow_status(db_id, FlowStatus.DELETED)

        return {
            "success": True,
            "message": f"Deleted {len(flows_to_delete)} flow(s) from {node_id}",
            "node_id": node_id, "table_id": table_id,
            "flows_deleted": flows_to_delete,
            "odl_results": odl_results,
        }

    # ============================================================
    # Hard Delete Flow (DB Only)
    # ============================================================

    async def hard_delete_flow(self, flow_rule_id: str) -> Dict[str, Any]:
        """ลบ Flow Rule ออกจาก Database อย่างถาวร (Hard Delete)"""
        prisma = get_prisma_client()
        record = await prisma.flowrule.find_unique(where={"id": flow_rule_id})

        if not record:
            raise ValueError(f"FlowRule '{flow_rule_id}' not found")
            
        # บังคับห้าม Hard Delete ถ้า Flow ยังทำงานอยู่หรือรอดำเนินการ
        if record.status in [FlowStatus.ACTIVE, FlowStatus.PENDING]:
            raise ValueError(
                f"Cannot hard delete flow '{record.flow_id}' because its status is {record.status}. "
                "Please delete/deactivate it from the switch first."
            )

        await prisma.flowrule.delete(where={"id": flow_rule_id})
        
        # ลบคู่ (pair) ด้วยถ้ามี
        if record.pair_flow_id:
            pair = await prisma.flowrule.find_first(
                where={"flow_id": record.pair_flow_id, "node_id": record.node_id}
            )
            if pair:
                await prisma.flowrule.delete(where={"id": pair.id})
                logger.info(f"Hard deleted paired flow: {pair.flow_id}")

        logger.info(f"Hard deleted flow from DB: {record.flow_id} (ID: {flow_rule_id})")
        return {
            "success": True,
            "message": f"Flow '{record.flow_id}' permanently deleted from database",
            "flow_rule_id": flow_rule_id,
            "flow_id": record.flow_id,
            "node_id": record.node_id
        }

    # ============================================================
    # Reset Table (clear ODL + DB)
    # ============================================================

    async def reset_table(
        self, node_id: str, table_id: int = 0,
    ) -> Dict[str, Any]:
        """ล้าง Flow ทั้งหมดใน table — ODL + DB"""
        await self._validate_device(node_id)
        prisma = get_prisma_client()

        logger.warning(f"Flow RESET TABLE: {node_id}, table={table_id} — clearing ALL flows")

        # ① DELETE table จาก ODL
        path = (
            f"{self.INVENTORY_BASE}/node={node_id}"
            f"/flow-node-inventory:table={table_id}"
        )
        spec = RequestSpec(
            method="DELETE", datastore="config", path=path,
            payload=None, headers={"Accept": "application/json"},
        )
        odl_result = await self.odl_client.send(spec)

        # ② UPDATE DB → DELETED ทุก ACTIVE/PENDING flow ของ node+table นี้
        updated = await prisma.flowrule.update_many(
            where={
                "node_id": node_id,
                "table_id": table_id,
                "status": {"in": [FlowStatus.ACTIVE, FlowStatus.PENDING]},
            },
            data={"status": FlowStatus.DELETED},
        )

        return {
            "success": True,
            "message": f"All flows in table {table_id} cleared from {node_id} ({updated} DB records updated)",
            "node_id": node_id, "table_id": table_id,
            "db_records_updated": updated,
            "odl_response": odl_result,
        }

    # ============================================================
    # Get Flows (from ODL)
    # ============================================================

    async def get_flows(
        self, node_id: str, table_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """ดึง Flow Rules ทั้งหมดใน table จาก ODL (raw YANG data)"""
        await self._validate_device(node_id)
        logger.info(f"Flow GET: {node_id}, table={table_id or 'all'}")

        if table_id is not None:
            path = (
                f"{self.INVENTORY_BASE}/node={node_id}"
                f"/flow-node-inventory:table={table_id}"
            )
        else:
            path = f"{self.INVENTORY_BASE}/node={node_id}"

        spec = RequestSpec(
            method="GET", datastore="config", path=path,
            payload=None, headers={"Accept": "application/json"},
        )
        result = await self.odl_client.send(spec)

        return {
            "success": True,
            "message": f"Flows retrieved from {node_id}",
            "node_id": node_id, "table_id": table_id,
            "flows": result,
        }

    async def get_flow_by_id(
        self, node_id: str, flow_id: str, table_id: int = 0,
    ) -> Dict[str, Any]:
        """ดึง Flow เฉพาะตัวจาก ODL (specific flow detail)"""
        await self._validate_device(node_id)
        logger.info(f"Flow GET [specific]: {flow_id} on {node_id}, table={table_id}")

        path = (
            f"{self.INVENTORY_BASE}/node={node_id}"
            f"/flow-node-inventory:table={table_id}"
            f"/flow={flow_id}"
        )
        spec = RequestSpec(
            method="GET", datastore="config", path=path,
            payload=None, headers={"Accept": "application/json"},
        )
        result = await self.odl_client.send(spec)

        return {
            "success": True,
            "message": f"Flow '{flow_id}' retrieved from {node_id}",
            "node_id": node_id, "table_id": table_id,
            "flow_id": flow_id, "flow": result,
        }

    # ============================================================
    # Get Flow Rules (from DB — for Dashboard)
    # ============================================================

    async def get_flow_rules(
        self,
        node_id: Optional[str] = None,
        status: Optional[str] = None,
        flow_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """ดึง FlowRule จาก DB — structured, fast, for Dashboard"""
        prisma = get_prisma_client()

        where: Dict[str, Any] = {}
        if node_id:
            where["node_id"] = node_id
        if status:
            where["status"] = status
        if flow_type:
            where["flow_type"] = flow_type

        records = await prisma.flowrule.find_many(
            where=where,
            order={"createdAt": "desc"},
        )

        return [
            {
                "id": r.id,
                "flow_id": r.flow_id,
                "node_id": r.node_id,
                "table_id": r.table_id,
                "flow_type": r.flow_type,
                "priority": r.priority,
                "bidirectional": r.bidirectional,
                "pair_flow_id": r.pair_flow_id,
                "direction": r.direction,
                "match_details": r.match_details,
                "status": r.status,
                "created_at": r.createdAt.isoformat() if r.createdAt else None,
                "updated_at": r.updatedAt.isoformat() if r.updatedAt else None,
            }
            for r in records
        ]

    # ============================================================
    # Sync Flow Rules (compare DB ↔ ODL)
    # ============================================================

    async def sync_flow_rules(
        self, node_id: str, table_id: int = 0,
    ) -> Dict[str, Any]:
        """
        เทียบ FlowRule ใน DB กับ Flow จริงใน ODL config datastore

        ตรวจจับ:
        - zombie: DB ยัง ACTIVE แต่ ODL ไม่มีแล้ว → mark DELETED
        - unmanaged: ODL มี แต่ DB ไม่มี → report (ไม่ได้สร้างผ่าน Backend)
        """
        await self._validate_device(node_id)
        prisma = get_prisma_client()

        logger.info(f"Flow SYNC: {node_id}, table={table_id}")

        # ① ดึง flows จาก ODL config
        odl_flow_ids = set()
        try:
            path = (
                f"{self.INVENTORY_BASE}/node={node_id}"
                f"/flow-node-inventory:table={table_id}"
            )
            spec = RequestSpec(
                method="GET", datastore="config", path=path,
                payload=None, headers={"Accept": "application/json"},
            )
            result = await self.odl_client.send(spec)

            # Parse flow IDs จาก ODL response
            table_data = result.get("flow-node-inventory:table", [])
            if isinstance(table_data, list):
                for table in table_data:
                    for flow in table.get("flow", []):
                        odl_flow_ids.add(flow.get("id", ""))
            elif isinstance(table_data, dict):
                for flow in table_data.get("flow", []):
                    odl_flow_ids.add(flow.get("id", ""))

        except Exception as e:
            logger.warning(f"Could not fetch ODL flows for {node_id}: {e}")
            # ถ้า ODL ไม่ตอบ (เช่น table ว่าง) → ถือว่า ODL ไม่มี flow
            odl_flow_ids = set()

        # ② ดึง ACTIVE flows จาก DB
        db_flows = await prisma.flowrule.find_many(
            where={
                "node_id": node_id,
                "table_id": table_id,
                "status": FlowStatus.ACTIVE,
            }
        )
        db_flow_ids = {f.flow_id for f in db_flows}

        # ③ เทียบ
        zombies = []  # DB มี แต่ ODL ไม่มี
        unmanaged = []  # ODL มี แต่ DB ไม่มี

        # Zombie: DB ACTIVE → ODL ไม่มี → mark DELETED
        for db_flow in db_flows:
            if db_flow.flow_id not in odl_flow_ids:
                await self._update_flow_status(db_flow.id, FlowStatus.DELETED)
                zombies.append(db_flow.flow_id)
                logger.info(f"Flow SYNC [zombie]: {db_flow.flow_id} → DELETED")

        # Unmanaged: ODL มี → DB ไม่มี (สร้างนอก Backend)
        for odl_fid in odl_flow_ids:
            if odl_fid and odl_fid not in db_flow_ids:
                unmanaged.append(odl_fid)

        return {
            "success": True,
            "message": (
                f"Sync complete for {node_id}: "
                f"{len(zombies)} zombie(s) cleaned, {len(unmanaged)} unmanaged"
            ),
            "node_id": node_id,
            "table_id": table_id,
            "odl_flow_count": len(odl_flow_ids),
            "db_active_count": len(db_flow_ids),
            "zombies_cleaned": zombies,
            "unmanaged_flows": unmanaged,
        }

    # ============================================================
    # Retry FAILED Flow
    # ============================================================

    async def retry_flow(self, flow_rule_id: str) -> Dict[str, Any]:
        """Retry FAILED flow — ลอง PUT ไป ODL อีกครั้ง"""
        prisma = get_prisma_client()
        record = await prisma.flowrule.find_unique(where={"id": flow_rule_id})

        if not record:
            raise ValueError(f"FlowRule '{flow_rule_id}' not found")
        if record.status != FlowStatus.FAILED:
            raise ValueError(f"FlowRule '{flow_rule_id}' is {record.status}, not FAILED")

        # Rebuild payload from match_details
        match = record.match_details or {}
        payload = self._rebuild_payload(record, match)

        # Update to PENDING before retrying
        await self._update_flow_status(record.id, FlowStatus.PENDING)

        try:
            result = await self._push_flow_to_odl(
                record.flow_id, record.node_id, record.table_id, payload,
            )
            await self._update_flow_status(record.id, FlowStatus.ACTIVE)

            return {
                "success": True,
                "message": f"Flow '{record.flow_id}' retried successfully → ACTIVE",
                "flow_rule_id": record.id,
                "flow_id": record.flow_id,
                "node_id": record.node_id,
                "status": "ACTIVE",
                "odl_response": result,
            }
        except Exception as e:
            await self._update_flow_status(record.id, FlowStatus.FAILED)
            raise

    # ============================================================
    # Reactivate DELETED Flow
    # ============================================================

    async def reactivate_flow(self, flow_rule_id: str) -> Dict[str, Any]:
        """เปิดใช้งาน Flow ที่เคยถูกลบไปแล้วกลับมาใหม่"""
        prisma = get_prisma_client()
        record = await prisma.flowrule.find_unique(where={"id": flow_rule_id})

        if not record:
            raise ValueError(f"FlowRule '{flow_rule_id}' not found")
        if record.status != FlowStatus.DELETED:
            raise ValueError(f"FlowRule '{flow_rule_id}' is {record.status}. Only DELETED flows can be reactivated.")

        # Rebuild payload from match_details
        match = record.match_details or {}
        payload = self._rebuild_payload(record, match)

        # Update to PENDING before retrying
        await self._update_flow_status(record.id, FlowStatus.PENDING)

        try:
            result = await self._push_flow_to_odl(
                record.flow_id, record.node_id, record.table_id, payload,
            )
            await self._update_flow_status(record.id, FlowStatus.ACTIVE)

            return {
                "success": True,
                "message": f"Flow '{record.flow_id}' reactivated successfully → ACTIVE",
                "flow_rule_id": record.id,
                "flow_id": record.flow_id,
                "node_id": record.node_id,
                "status": "ACTIVE",
                "odl_response": result,
            }
        except Exception as e:
            await self._update_flow_status(record.id, FlowStatus.FAILED)
            raise

    def _rebuild_payload(self, record, match: dict) -> Dict[str, Any]:
        """Rebuild ODL payload จาก FlowRule record + match_details"""
        ft = record.flow_type

        if ft == "arp_flood":
            return self._build_arp_flood_payload(record.flow_id, record.table_id, record.priority)
        elif ft == "base_connectivity":
            return self._build_wiring_payload(
                record.flow_id, record.table_id, record.priority,
                str(match.get("in_port", "")), str(match.get("out_port", "")),
            )
        elif ft == "traffic_steering":
            return self._build_steering_payload(
                record.flow_id, record.table_id, record.priority,
                str(match.get("in_port", "")), str(match.get("out_port", "")),
                match.get("dst_port", match.get("tcp_dst_port", 0)),
                match.get("protocol", "tcp"),
            )
        elif ft == "acl_mac_drop":
            return self._build_acl_mac_drop_payload(
                record.flow_id, record.table_id, record.priority, match.get("src_mac", ""),
            )
        elif ft == "acl_ip_blacklist":
            return self._build_acl_ip_blacklist_payload(
                record.flow_id, record.table_id, record.priority,
                match.get("src_ip", ""), match.get("dst_ip", ""),
            )
        elif ft == "acl_port_drop":
            return self._build_acl_port_drop_payload(
                record.flow_id, record.table_id, record.priority,
                match.get("dst_port", match.get("tcp_dst_port", 0)),
                match.get("protocol", "tcp"),
            )
        elif ft == "acl_whitelist":
            return self._build_acl_whitelist_payload(
                record.flow_id, record.table_id, record.priority,
                match.get("dst_port", match.get("tcp_dst_port", 0)),
                match.get("protocol", "tcp"),
            )
        elif ft == "mac_steering":
            return self._build_mac_steering_payload(
                record.flow_id, record.table_id, record.priority,
                match.get("src_mac", ""), str(match.get("out_port", "")),
            )
        elif ft == "ip_steering":
            return self._build_ip_steering_payload(
                record.flow_id, record.table_id, record.priority,
                match.get("dst_ip", ""), str(match.get("out_port", "")),
            )
        elif ft == "default_gateway":
            return self._build_default_gw_payload(
                record.flow_id, record.table_id, record.priority, str(match.get("out_port", "")),
            )
        elif ft == "subnet_steering":
            return self._build_subnet_steering_payload(
                record.flow_id, record.table_id, record.priority,
                match.get("src_ip_subnet", ""), str(match.get("out_port", "")),
            )
        elif ft == "icmp_control":
            return self._build_icmp_payload(
                record.flow_id, record.table_id, record.priority, match.get("action", "DROP"),
            )
        else:
            raise ValueError(f"Unknown flow_type: {ft}")

    # ============================================================
    # Payload Builders (OpenFlow 1.3 YANG Model)
    # ============================================================

    @staticmethod
    def _build_arp_flood_payload(flow_id: str, table_id: int, priority: int) -> Dict[str, Any]:
        """ARP Flood — Match ethernet-type=0x0806(ARP) → FLOOD"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {"ethernet-match": {"ethernet-type": {"type": 2054}}},
                "instructions": {"instruction": [{"order": 0, "apply-actions": {
                    "action": [{"order": 0, "output-action": {"output-node-connector": "FLOOD"}}]
                }}]},
            }]
        }

    @staticmethod
    def _build_wiring_payload(flow_id: str, table_id: int, priority: int,
                              inbound_port: str, outbound_port: str) -> Dict[str, Any]:
        """Base Wiring — Match in-port → output"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {"in-port": inbound_port},
                "instructions": {"instruction": [{"order": 0, "apply-actions": {
                    "action": [{"order": 0, "output-action": {"output-node-connector": outbound_port}}]
                }}]},
            }]
        }

    @staticmethod
    def _build_steering_payload(flow_id: str, table_id: int, priority: int,
                                inbound_port: str, outbound_port: str,
                                dst_port: int, protocol: str = "tcp") -> Dict[str, Any]:
        """Traffic Steering — Match in-port + IPv4 + TCP/UDP + dst-port → output"""
        ip_proto = 6 if protocol == "tcp" else 17
        port_key = "tcp-destination-port" if protocol == "tcp" else "udp-destination-port"
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {
                    "in-port": inbound_port,
                    "ethernet-match": {"ethernet-type": {"type": 2048}},
                    "ip-match": {"ip-protocol": ip_proto},
                    port_key: dst_port,
                },
                "instructions": {"instruction": [{"order": 0, "apply-actions": {
                    "action": [{"order": 0, "output-action": {"output-node-connector": outbound_port}}]
                }}]},
            }]
        }

    @staticmethod
    def _build_acl_mac_drop_payload(flow_id: str, table_id: int, priority: int,
                                    src_mac: str) -> Dict[str, Any]:
        """L2 ACL — Match ethernet-source → DROP (no instructions)"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {"ethernet-match": {"ethernet-source": {"address": src_mac}}},
            }]
        }

    @staticmethod
    def _build_acl_ip_blacklist_payload(flow_id: str, table_id: int, priority: int,
                                        src_ip: str, dst_ip: str) -> Dict[str, Any]:
        """L3 ACL — Match IPv4 + src-ip + dst-ip → DROP"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {
                    "ethernet-match": {"ethernet-type": {"type": 2048}},
                    "ipv4-source": src_ip,
                    "ipv4-destination": dst_ip,
                },
            }]
        }

    @staticmethod
    def _build_acl_port_drop_payload(flow_id: str, table_id: int, priority: int,
                                     dst_port: int, protocol: str = "tcp") -> Dict[str, Any]:
        """L4 ACL — Match IPv4 + TCP/UDP + dst-port → DROP"""
        ip_proto = 6 if protocol == "tcp" else 17
        port_key = "tcp-destination-port" if protocol == "tcp" else "udp-destination-port"
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {
                    "ethernet-match": {"ethernet-type": {"type": 2048}},
                    "ip-match": {"ip-protocol": ip_proto},
                    port_key: dst_port,
                },
            }]
        }

    @staticmethod
    def _build_acl_whitelist_payload(flow_id: str, table_id: int, priority: int,
                                     dst_port: int, protocol: str = "tcp") -> Dict[str, Any]:
        """Whitelist — Match IPv4 + TCP/UDP + dst-port → output NORMAL"""
        ip_proto = 6 if protocol == "tcp" else 17
        port_key = "tcp-destination-port" if protocol == "tcp" else "udp-destination-port"
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {
                    "ethernet-match": {"ethernet-type": {"type": 2048}},
                    "ip-match": {"ip-protocol": ip_proto},
                    port_key: dst_port,
                },
                "instructions": {"instruction": [{"order": 0, "apply-actions": {
                    "action": [{"order": 0, "output-action": {"output-node-connector": "NORMAL"}}]
                }}]},
            }]
        }

    @staticmethod
    def _build_mac_steering_payload(flow_id: str, table_id: int, priority: int,
                                    src_mac: str, outbound_port: str) -> Dict[str, Any]:
        """L2 MAC Steering — Match ethernet-source → output"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {"ethernet-match": {"ethernet-source": {"address": src_mac}}},
                "instructions": {"instruction": [{"order": 0, "apply-actions": {
                    "action": [{"order": 0, "output-action": {"output-node-connector": outbound_port}}]
                }}]},
            }]
        }

    @staticmethod
    def _build_ip_steering_payload(flow_id: str, table_id: int, priority: int,
                                   dst_ip: str, outbound_port: str) -> Dict[str, Any]:
        """L3 IP Steering — Match IPv4 + ipv4-destination → output"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {
                    "ethernet-match": {"ethernet-type": {"type": 2048}},
                    "ipv4-destination": dst_ip,
                },
                "instructions": {"instruction": [{"order": 0, "apply-actions": {
                    "action": [{"order": 0, "output-action": {"output-node-connector": outbound_port}}]
                }}]},
            }]
        }

    @staticmethod
    def _build_default_gw_payload(flow_id: str, table_id: int, priority: int,
                                  outbound_port: str) -> Dict[str, Any]:
        """Default Gateway — Match IPv4 → output"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {
                    "ethernet-match": {"ethernet-type": {"type": 2048}},
                },
                "instructions": {"instruction": [{"order": 0, "apply-actions": {
                    "action": [{"order": 0, "output-action": {"output-node-connector": outbound_port}}]
                }}]},
            }]
        }

    @staticmethod
    def _build_subnet_steering_payload(flow_id: str, table_id: int, priority: int,
                                       src_subnet: str, outbound_port: str) -> Dict[str, Any]:
        """L3 Subnet Steering — Match IPv4 + ipv4-source → output"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {
                    "ethernet-match": {"ethernet-type": {"type": 2048}},
                    "ipv4-source": src_subnet,
                },
                "instructions": {"instruction": [{"order": 0, "apply-actions": {
                    "action": [{"order": 0, "output-action": {"output-node-connector": outbound_port}}]
                }}]},
            }]
        }

    @staticmethod
    def _build_icmp_payload(flow_id: str, table_id: int, priority: int,
                            action: str) -> Dict[str, Any]:
        """L3 ICMP Control — Match IPv4 + ICMP → DROP or NORMAL"""
        flow_dict: Dict[str, Any] = {
            "id": flow_id, "table_id": table_id, "priority": priority,
            "match": {
                "ethernet-match": {"ethernet-type": {"type": 2048}},
                "ip-match": {"ip-protocol": 1},
            }
        }
        if action == "NORMAL":
            flow_dict["instructions"] = {"instruction": [{"order": 0, "apply-actions": {
                "action": [{"order": 0, "output-action": {"output-node-connector": "NORMAL"}}]
            }}]}
        
        return {
            "flow-node-inventory:flow": [flow_dict]
        }

    # ============================================================
    # Flow Templates Metadata (For Frontend Wizard)
    # ============================================================

    @staticmethod
    def get_flow_templates() -> Dict[str, Any]:
        """ดึง Template ของ Flow ทั้งหมดสำหรับวาด UI หน้าเว็บ"""
        return {
            "success": True,
            "total_templates": 12,
            "categories": [
                {
                    "id": "connectivity",
                    "label": "🔌 Connectivity",
                    "description": "การเชื่อมต่อพื้นฐานระหว่างพอร์ต",
                    "templates": [
                        {
                            "id": "arp_flood",
                            "label": "ARP Flood",
                            "description": "กระจาย ARP ทุกพอร์ต เพื่อให้ Host คุยกันได้ (Priority 400)",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/connectivity/arp-flood",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 400, "required": False}
                            ]
                        },
                        {
                            "id": "base_connectivity",
                            "label": "Base Connectivity",
                            "description": "เชื่อม L1 Forwarding ระหว่าง 2 พอร์ต (Priority 500)",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/connectivity/base",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "inbound_interface_id", "label": "Inbound Port", "type": "interface_select", "required": True},
                                {"name": "outbound_interface_id", "label": "Outbound Port", "type": "interface_select", "required": True},
                                {"name": "bidirectional", "label": "Bidirectional (สร้างขากลับด้วย)", "type": "boolean", "default": True, "required": False},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 500, "required": False}
                            ]
                        },
                        {
                            "id": "default_gateway",
                            "label": "Default Gateway",
                            "description": "ทราฟฟิกที่ไม่ตรงกับกฎใดๆ ให้ส่งออกไปยัง Gateway Port (Priority 100)",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/connectivity/default-gateway",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "outbound_interface_id", "label": "Gateway Port", "type": "interface_select", "required": True},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 100, "required": False}
                            ]
                        }
                    ]
                },
                {
                    "id": "steering",
                    "label": "🎯 Traffic Steering",
                    "description": "เปลี่ยนเส้นทางทราฟฟิก (Redirect)",
                    "templates": [
                        {
                            "id": "steer_l4_port",
                            "label": "L4 Port Redirect (TCP/UDP)",
                            "description": "บังคับ Traffic ของพอร์ต TCP/UDP เฉพาะ ให้ไปออกพอร์ตที่กำหนด",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/steering/l4-port",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "inbound_interface_id", "label": "Inbound Port", "type": "interface_select", "required": True},
                                {"name": "outbound_interface_id", "label": "Redirect To Port", "type": "interface_select", "required": True},
                                {"name": "protocol", "label": "Protocol", "type": "protocol_select", "options": ["tcp", "udp"], "default": "tcp", "required": False},
                                {"name": "dst_port", "label": "Destination Port", "type": "number", "min": 1, "max": 65535, "required": True},
                                {"name": "bidirectional", "label": "Bidirectional (สร้างขากลับด้วย)", "type": "boolean", "default": True, "required": False},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 600, "required": False}
                            ]
                        },
                        {
                            "id": "steer_l2_mac",
                            "label": "L2 MAC Redirect",
                            "description": "บังคับ Traffic จาก Source MAC Address ให้ไปออกพอร์ตที่กำหนด",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/steering/l2-mac",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "src_mac", "label": "Source MAC Address", "type": "mac", "required": True},
                                {"name": "outbound_interface_id", "label": "Redirect To Port", "type": "interface_select", "required": True},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 960, "required": False}
                            ]
                        },
                        {
                            "id": "steer_l3_ip",
                            "label": "L3 IP Redirect",
                            "description": "บังคับ Traffic ที่ไปหา Destination IP ให้ไปออกพอร์ตที่กำหนด",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/steering/l3-ip",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "dst_ip", "label": "Destination IP (CIDR)", "type": "ip_cidr", "required": True},
                                {"name": "outbound_interface_id", "label": "Redirect To Port", "type": "interface_select", "required": True},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 960, "required": False}
                            ]
                        },
                        {
                            "id": "steer_l3_subnet",
                            "label": "L3 Subnet Redirect",
                            "description": "แยกเส้นทางตามกลุ่ม IP ต้นทาง (Source IP Subnet) ให้ไปออกพอร์ตที่กำหนด",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/steering/l3-subnet",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "src_ip_subnet", "label": "Source IP Subnet (CIDR)", "type": "ip_cidr", "required": True},
                                {"name": "outbound_interface_id", "label": "Redirect To Port", "type": "interface_select", "required": True},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 960, "required": False}
                            ]
                        }
                    ]
                },
                {
                    "id": "security",
                    "label": "🛡️ Security (ACL)",
                    "description": "บล็อกหรืออนุญาตทราฟฟิก (Drop / Allow)",
                    "templates": [
                        {
                            "id": "acl_mac_drop",
                            "label": "Block MAC Address",
                            "description": "บล็อกทราฟฟิกทั้งหมดที่มาจาก Source MAC นี้",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/acl/block-mac",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "src_mac", "label": "Source MAC Address", "type": "mac", "required": True},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 1100, "required": False}
                            ]
                        },
                        {
                            "id": "acl_ip_blacklist",
                            "label": "Block IP Pair",
                            "description": "บล็อกการสื่อสารระหว่าง Source IP และ Destination IP",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/acl/block-ip",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "src_ip", "label": "Source IP (CIDR)", "type": "ip_cidr", "required": True},
                                {"name": "dst_ip", "label": "Destination IP (CIDR)", "type": "ip_cidr", "required": True},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 1100, "required": False}
                            ]
                        },
                        {
                            "id": "acl_port_drop",
                            "label": "Block Port (TCP/UDP)",
                            "description": "บล็อกทราฟฟิกที่วิ่งเข้าหา Destination Port นี้ (เช่น บล็อกพอร์ต 80)",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/acl/block-port",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "protocol", "label": "Protocol", "type": "protocol_select", "options": ["tcp", "udp"], "default": "tcp", "required": False},
                                {"name": "dst_port", "label": "Destination Port", "type": "number", "min": 1, "max": 65535, "required": True},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 1200, "required": False}
                            ]
                        },
                        {
                            "id": "acl_port_whitelist",
                            "label": "Whitelist Port (TCP/UDP)",
                            "description": "อนุญาตทราฟฟิกขาเข้าสำหรับพอร์ตนี้ (ไว้ใช้คู่กับการล็อกพอร์ตอื่นทิ้ง)",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/acl/whitelist-port",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "protocol", "label": "Protocol", "type": "protocol_select", "options": ["tcp", "udp"], "default": "tcp", "required": False},
                                {"name": "dst_port", "label": "Destination Port", "type": "number", "min": 1, "max": 65535, "required": True},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 1000, "required": False}
                            ]
                        },
                        {
                            "id": "acl_icmp_control",
                            "label": "ICMP Control (Ping)",
                            "description": "ตั้งค่าอนุญาตหรือบล็อกการส่ง Ping (ICMP Echo) ทั้งระบบ",
                            "endpoint": "/api/v1/nbi/devices/{node_id}/flows/acl/icmp-control",
                            "method": "POST",
                            "fields": [
                                {"name": "flow_id", "label": "Flow ID", "type": "string", "required": True},
                                {"name": "node_id", "label": "Device", "type": "device_select", "required": True},
                                {"name": "action", "label": "Action", "type": "protocol_select", "options": ["DROP", "NORMAL"], "default": "DROP", "required": True},
                                {"name": "priority", "label": "Priority", "type": "number", "default": 1100, "required": False}
                            ]
                        }
                    ]
                }
            ]
        }
