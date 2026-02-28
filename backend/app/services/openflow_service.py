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
        return await prisma.flowrule.create(
            data={
                "flow_id": flow_id,
                "node_id": node_id,
                "table_id": table_id,
                "flow_type": flow_type,
                "priority": priority,
                "bidirectional": bidirectional,
                "pair_flow_id": pair_flow_id,
                "direction": direction,
                "match_details": match_details if match_details else {},
                "status": FlowStatus.PENDING,
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
        tcp_dst_port: int, priority: int = 600,
        table_id: int = 0, bidirectional: bool = True,
    ) -> Dict[str, Any]:
        """Traffic Steering — L4 TCP Redirect (bidirectional by default)"""
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
                match_details={"in_port": int(in_port), "out_port": int(out_port), "tcp_dst_port": tcp_dst_port},
            )
            rev_db = await self._save_flow_to_db(
                rev_id, node_id, table_id, "traffic_steering", priority,
                bidirectional=True, pair_flow_id=fwd_id, direction="reverse",
                match_details={"in_port": int(out_port), "out_port": int(in_port), "tcp_dst_port": tcp_dst_port},
            )

            logger.info(f"Flow ADD [steer-fwd]: {fwd_id} on {node_id} | TCP:{tcp_dst_port}")
            fwd_payload = self._build_steering_payload(fwd_id, table_id, priority, in_port, out_port, tcp_dst_port)
            fwd_result = await self._push_and_track(fwd_db, fwd_id, node_id, table_id, fwd_payload)
            flows_created.append({
                "flow_id": fwd_id, "direction": "forward", "tcp_dst_port": tcp_dst_port,
                "flow_rule_id": fwd_db.id, "odl_response": fwd_result,
            })

            logger.info(f"Flow ADD [steer-rev]: {rev_id} on {node_id} | TCP:{tcp_dst_port}")
            rev_payload = self._build_steering_payload(rev_id, table_id, priority, out_port, in_port, tcp_dst_port)
            rev_result = await self._push_and_track(rev_db, rev_id, node_id, table_id, rev_payload)
            flows_created.append({
                "flow_id": rev_id, "direction": "reverse", "tcp_dst_port": tcp_dst_port,
                "flow_rule_id": rev_db.id, "odl_response": rev_result,
            })
        else:
            logger.info(f"Flow ADD [steer]: {flow_id} on {node_id} | TCP:{tcp_dst_port}")
            db_record = await self._save_flow_to_db(
                flow_id, node_id, table_id, "traffic_steering", priority,
                match_details={"in_port": int(in_port), "out_port": int(out_port), "tcp_dst_port": tcp_dst_port},
            )
            payload = self._build_steering_payload(flow_id, table_id, priority, in_port, out_port, tcp_dst_port)
            result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)
            flows_created.append({
                "flow_id": flow_id, "direction": "forward", "tcp_dst_port": tcp_dst_port,
                "flow_rule_id": db_record.id, "odl_response": result,
            })

        direction_text = "bidirectional" if bidirectional else "unidirectional"
        return {
            "success": True, "flow_type": "traffic_steering",
            "message": f"Traffic steering '{flow_id}' on {node_id} — TCP:{tcp_dst_port} ({direction_text})",
            "node_id": node_id, "tcp_dst_port": tcp_dst_port, "bidirectional": bidirectional,
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
        self, flow_id: str, node_id: str, tcp_dst_port: int,
        priority: int = 1200, table_id: int = 0,
    ) -> Dict[str, Any]:
        """L4 ACL — Drop traffic ที่ไปหา TCP destination port"""
        await self._validate_device(node_id)
        logger.info(f"Flow ADD [acl-port-drop]: {flow_id} on {node_id} | TCP:{tcp_dst_port}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "acl_port_drop", priority,
            match_details={"tcp_dst_port": tcp_dst_port},
        )
        payload = self._build_acl_port_drop_payload(flow_id, table_id, priority, tcp_dst_port)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "acl_port_drop",
            "message": f"ACL port drop '{flow_id}' on {node_id}: TCP:{tcp_dst_port} → DROP",
            "flow_id": flow_id, "node_id": node_id, "tcp_dst_port": tcp_dst_port,
            "flow_rule_id": db_record.id, "odl_response": result,
        }

    # ============================================================
    # 4d. ACL: Whitelist
    # ============================================================

    async def add_acl_whitelist(
        self, flow_id: str, node_id: str, tcp_dst_port: int,
        priority: int = 1000, table_id: int = 0,
    ) -> Dict[str, Any]:
        """Whitelist — อนุญาตเฉพาะ TCP port (output NORMAL)"""
        await self._validate_device(node_id)
        logger.info(f"Flow ADD [acl-whitelist]: {flow_id} on {node_id} | TCP:{tcp_dst_port}")

        db_record = await self._save_flow_to_db(
            flow_id, node_id, table_id, "acl_whitelist", priority,
            match_details={"tcp_dst_port": tcp_dst_port},
        )
        payload = self._build_acl_whitelist_payload(flow_id, table_id, priority, tcp_dst_port)
        result = await self._push_and_track(db_record, flow_id, node_id, table_id, payload)

        return {
            "success": True, "flow_type": "acl_whitelist",
            "message": f"ACL whitelist '{flow_id}' on {node_id}: TCP:{tcp_dst_port} → PERMIT",
            "flow_id": flow_id, "node_id": node_id, "tcp_dst_port": tcp_dst_port,
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
        """ดึง Flow Rules จาก ODL (raw YANG data)"""
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
                match.get("tcp_dst_port", 0),
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
                record.flow_id, record.table_id, record.priority, match.get("tcp_dst_port", 0),
            )
        elif ft == "acl_whitelist":
            return self._build_acl_whitelist_payload(
                record.flow_id, record.table_id, record.priority, match.get("tcp_dst_port", 0),
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
                                tcp_dst_port: int) -> Dict[str, Any]:
        """Traffic Steering — Match in-port + IPv4 + TCP + dst-port → output"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {
                    "in-port": inbound_port,
                    "ethernet-match": {"ethernet-type": {"type": 2048}},
                    "ip-match": {"ip-protocol": 6},
                    "tcp-destination-port": tcp_dst_port,
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
                                     tcp_dst_port: int) -> Dict[str, Any]:
        """L4 ACL — Match IPv4 + TCP + dst-port → DROP"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {
                    "ethernet-match": {"ethernet-type": {"type": 2048}},
                    "ip-match": {"ip-protocol": 6},
                    "tcp-destination-port": tcp_dst_port,
                },
            }]
        }

    @staticmethod
    def _build_acl_whitelist_payload(flow_id: str, table_id: int, priority: int,
                                     tcp_dst_port: int) -> Dict[str, Any]:
        """Whitelist — Match IPv4 + TCP + dst-port → output NORMAL"""
        return {
            "flow-node-inventory:flow": [{
                "id": flow_id, "table_id": table_id, "priority": priority,
                "match": {
                    "ethernet-match": {"ethernet-type": {"type": 2048}},
                    "ip-match": {"ip-protocol": 6},
                    "tcp-destination-port": tcp_dst_port,
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
