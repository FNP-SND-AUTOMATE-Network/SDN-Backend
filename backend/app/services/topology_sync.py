"""
Service for syncing Topology from OpenDaylight to Database (Prisma)
"""
import re
import requests
from typing import Dict, Any, List, Set, Tuple, Optional
from app.core.config import settings
from app.core.logging import logger
from app.database import get_prisma_client


# ── Helper: Expand abbreviated interface names ──────────────
def _expand_interface_name(name: str) -> str:
    """Expand Cisco/Huawei abbreviated interface names to full form."""
    if not name:
        return name
    if name.startswith("Gi") and not name.startswith("Gigabit"):
        return name.replace("Gi", "GigabitEthernet", 1)
    if name.startswith("Te") and not name.startswith("Ten"):
        return name.replace("Te", "TenGigabitEthernet", 1)
    if name.startswith("Fa") and not name.startswith("Fast"):
        return name.replace("Fa", "FastEthernet", 1)
    if name.startswith("Eth") and not name.startswith("Ethernet"):
        return name.replace("Eth", "Ethernet", 1)
    return name


# ── Helper: Build a comprehensive node-name → UUID resolver ─
async def _build_node_resolver(prisma, device_id_map: Dict[str, str]) -> Dict[str, str]:
    """
    สร้าง resolver map ที่ครอบคลุมหลายรูปแบบชื่อ → device UUID
    เพื่อให้ LLDP neighbor name (system-name / device-id) resolve กลับไปหา device ในระบบได้
    เฉพาะ device ที่ user สร้างเอง (exclude dummy/auto-discovered)
    """
    resolver: Dict[str, str] = dict(device_id_map)

    try:
        # ดึงเฉพาะ device จริง (exclude dummy จาก sync ก่อนหน้า)
        all_devices = await prisma.devicenetwork.find_many(
            where={
                "NOT": [
                    {"device_model": {"in": ["LLDP Neighbor (Auto-discovered)", "Unknown Neighbor"]}},
                    {"serial_number": {"startsWith": "DUMMY-SN-"}},
                    {"serial_number": {"startsWith": "LLDP-SN-"}},
                ]
            }
        )
        for d in all_devices:
            uid = d.id
            # Map by node_id (exact + lower)
            if d.node_id:
                resolver.setdefault(d.node_id, uid)
                resolver.setdefault(d.node_id.lower(), uid)
            # Map by device_name (hostname) + stripped domain
            if d.device_name:
                resolver.setdefault(d.device_name, uid)
                resolver.setdefault(d.device_name.lower(), uid)
                base_name = d.device_name.split('.')[0]
                resolver.setdefault(base_name, uid)
                resolver.setdefault(base_name.lower(), uid)
            # Map by MAC address (LLDP chassis-id อาจเป็น MAC)
            if d.mac_address and not d.mac_address.startswith(("OF-MAC-", "DUMMY-MAC-", "LLDP-MAC-")):
                mac_clean = d.mac_address.replace(":", "").replace(".", "").replace("-", "").lower()
                resolver.setdefault(mac_clean, uid)
                resolver.setdefault(d.mac_address.lower(), uid)
    except Exception as e:
        logger.error(f"Failed to build node resolver: {e}")

    return resolver


def _resolve_node(node_id: str, device_id_map: Dict[str, str], resolver: Dict[str, str]) -> Optional[str]:
    """
    พยายาม resolve node_id → device UUID ด้วยหลายกลยุทธ์:
    1. Direct match ใน device_id_map
    2. Direct match ใน resolver (device_name, hostname, MAC)
    3. Case-insensitive
    4. ตัด domain suffix แล้วลองใหม่
    """
    if node_id in device_id_map:
        return device_id_map[node_id]
    if node_id in resolver:
        return resolver[node_id]

    lower = node_id.lower()
    if lower in resolver:
        return resolver[lower]

    base = node_id.split('.')[0]
    if base in resolver:
        return resolver[base]
    if base.lower() in resolver:
        return resolver[base.lower()]

    return None


# ═════════════════════════════════════════════════════════════
#  Main Sync Function
# ═════════════════════════════════════════════════════════════
async def sync_odl_topology_to_db() -> Dict[str, Any]:
    """
    ดึงข้อมูล Topology จาก ODL (OpenFlow & NETCONF) และ Upsert ลง Database ให้ทันสมัยที่สุด
    คืนค่าสรุปผลการ Sync
    """
    prisma = get_prisma_client()

    # Credentials ODL (จาก .env)
    AUTH = (settings.ODL_USERNAME, settings.ODL_PASSWORD)
    HEADERS = {'Accept': 'application/json'}
    TIMEOUT = settings.ODL_TIMEOUT_SEC
    ODL_BASE = settings.ODL_BASE_URL.rstrip("/")

    logger.info(f"=== Topology Sync START  (ODL={ODL_BASE}) ===")

    # ---------------------------------------------------------
    # 1. รวบรวมข้อมูลดิบ (Raw Data) จาก ODL
    # ---------------------------------------------------------
    raw_nodes: Set[str] = set()
    raw_links: List[Dict[str, str]] = []

    # 1.1) ดึง Switch (OpenFlow) ──────────────────────────────
    # ดึงแบบไม่มี ?content=nonconfig เพื่อให้ได้ทั้ง nodes + links ครบถ้วน
    flow_url = f"{ODL_BASE}/rests/data/network-topology:network-topology/topology=flow:1"
    try:
        res_flow = requests.get(flow_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
        logger.info(f"[1.1] OpenFlow GET {flow_url} → HTTP {res_flow.status_code}")
        if res_flow.status_code == 200:
            flow_data = res_flow.json()
            topo_list = flow_data.get("network-topology:topology", flow_data.get("topology", []))
            if topo_list:
                topo_obj = topo_list[0]

                # Nodes
                for node in topo_obj.get("node", []):
                    nid = node["node-id"]
                    if nid.startswith("host:"):
                        continue
                    raw_nodes.add(nid)

                # Links (switch-to-switch)
                for link in topo_obj.get("link", []):
                    source_tp = link.get("source", {}).get("source-tp")
                    dest_tp = link.get("destination", {}).get("dest-tp")
                    link_id = link.get("link-id", f"{source_tp}-to-{dest_tp}")
                    if source_tp and dest_tp:
                        if source_tp.startswith("host:") or dest_tp.startswith("host:"):
                            continue
                        raw_links.append({
                            "link_id": link_id,
                            "source": source_tp,
                            "target": dest_tp,
                            "type": "OPENFLOW"
                        })

            logger.info(f"[1.1] OpenFlow: {len(raw_nodes)} switch nodes, {len(raw_links)} switch-to-switch links")
        else:
            logger.warning(f"[1.1] OpenFlow topology returned HTTP {res_flow.status_code}")
    except Exception as e:
        logger.error(f"[1.1] Failed to fetch OpenFlow Topology: {e}")

    # 1.1.1) Dedup bidirectional OpenFlow links (A→B + B→A → keep A→B)
    if raw_links:
        seen_of_pairs: Set[Tuple[str, str]] = set()
        deduped = []
        for ln in raw_links:
            pair = tuple(sorted([ln["source"], ln["target"]]))
            if pair in seen_of_pairs:
                continue
            seen_of_pairs.add(pair)
            deduped.append(ln)
        if len(deduped) < len(raw_links):
            logger.info(f"[1.1.1] Deduped OF bidirectional: {len(raw_links)} → {len(deduped)}")
            raw_links = deduped

    # 1.1.2) ดึง OpenFlow Inventory (status, ip, model ของ OF switches) ─
    of_inventory: Dict[str, Dict[str, Any]] = {}   # node_id → {ip_address, manufacturer, hardware, software, status, ports}
    if raw_nodes:
        inv_url = f"{ODL_BASE}/rests/data/opendaylight-inventory:nodes?content=nonconfig"
        try:
            res_inv = requests.get(inv_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
            logger.info(f"[1.1.2] OF Inventory GET {inv_url} → HTTP {res_inv.status_code}")
            if res_inv.status_code == 200:
                inv_data = res_inv.json()
                inv_nodes = inv_data.get("opendaylight-inventory:nodes", {}).get("node", [])
                for inv_node in inv_nodes:
                    nid = inv_node.get("id", "")
                    if not nid.startswith("openflow:"):
                        continue

                    ip_addr = inv_node.get("flow-node-inventory:ip-address")
                    manufacturer = inv_node.get("flow-node-inventory:manufacturer", "")
                    hardware = inv_node.get("flow-node-inventory:hardware", "")
                    software = inv_node.get("flow-node-inventory:software", "")
                    serial = inv_node.get("flow-node-inventory:serial-number", "")
                    description = inv_node.get("flow-node-inventory:description", "")

                    # สร้าง device_model จาก manufacturer + hardware
                    model_parts = [p for p in [manufacturer, hardware] if p and p != "None"]
                    device_model = " / ".join(model_parts) if model_parts else "OpenFlow Switch"

                    # สร้าง description จาก software version
                    desc_str = f"Software: {software}" if software and software != "None" else None
                    if description and description != "None":
                        desc_str = f"{description} | Software: {software}" if desc_str else description

                    # Node ปรากฏใน operational inventory = connected กับ controller = ONLINE
                    # (snapshot-gathering-status คือเรื่อง stats collection ไม่ใช่ connectivity)
                    is_online = True

                    # Parse port states จาก node-connector
                    port_states: Dict[str, str] = {}   # connector_id → "UP"/"DOWN"
                    for nc in inv_node.get("node-connector", []):
                        nc_id = nc.get("id", "")
                        nc_state = nc.get("flow-node-inventory:state", {})
                        link_down = nc_state.get("link-down", False)
                        port_states[nc_id] = "DOWN" if link_down else "UP"

                    of_inventory[nid] = {
                        "ip_address": ip_addr,
                        "device_model": device_model,
                        "description": desc_str,
                        "is_online": is_online,
                        "port_states": port_states,
                        "manufacturer": manufacturer,
                        "software": software,
                    }
                    logger.info(f"[1.1.2] {nid}: ip={ip_addr}, model={device_model}, online={is_online}, ports={len(port_states)}")
            else:
                logger.warning(f"[1.1.2] OF Inventory returned HTTP {res_inv.status_code}")
        except Exception as e:
            logger.error(f"[1.1.2] Failed to fetch OF Inventory: {e}")

    # 1.2) ดึง Router (NETCONF) LLDP ─────────────────────────
    # เฉพาะ device ที่ user สร้างเอง (exclude dummy ที่ถูกสร้างจาก sync ก่อนหน้า)
    try:
        netconf_devices = await prisma.devicenetwork.find_many(
            where={
                "management_protocol": "NETCONF",
                "node_id": {"not": None},
                "NOT": [
                    {"device_model": {"in": ["LLDP Neighbor (Auto-discovered)", "Unknown Neighbor"]}},
                    {"serial_number": {"startsWith": "DUMMY-SN-"}},
                    {"serial_number": {"startsWith": "LLDP-SN-"}},
                ]
            }
        )
        logger.info(f"[1.2] Found {len(netconf_devices)} NETCONF devices in DB")

        for device in netconf_devices:
            node_id = device.node_id
            if not node_id:
                continue

            lldp_neighbors_found = 0
            oc_success = False

            # ── ลองดึง LLDP ผ่าน OpenConfig ──
            oc_url = f"{ODL_BASE}/rests/data/network-topology:network-topology/topology=topology-netconf/node={node_id}/yang-ext:mount/openconfig-lldp:lldp/interfaces?content=nonconfig"
            try:
                res_oc = requests.get(oc_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
                if res_oc.status_code == 200:
                    raw_nodes.add(node_id)
                    oc_data = res_oc.json()
                    interfaces = oc_data.get("openconfig-lldp:interfaces", {}).get("interface", [])

                    for intf in interfaces:
                        local_port = intf.get("name")
                        neighbors = intf.get("neighbors", {}).get("neighbor", [])
                        for neighbor in neighbors:
                            state = neighbor.get("state", {})
                            remote_node = state.get("system-name")
                            remote_port = state.get("port-id")

                            if not remote_node or not remote_port:
                                logger.debug(f"  [{node_id}] {local_port}: neighbor missing system-name or port-id, skip")
                                continue

                            # Clean domain (CSR1000vT.lab.local → CSR1000vT)
                            # แต่ "openflow:1" ต้องเก็บไว้เต็ม
                            if "openflow" not in remote_node:
                                remote_node_clean = remote_node.split('.')[0]
                            else:
                                remote_node_clean = remote_node

                            # Handle "Not Advertised" port
                            remote_port_clean = remote_port
                            if remote_port_clean == "Not Advertised":
                                if "openflow" in remote_node:
                                    remote_port_clean = neighbor.get("id", "Unknown")
                                else:
                                    logger.debug(f"  [{node_id}] {local_port}: remote port 'Not Advertised', skip")
                                    continue

                            # Expand abbreviated interface names
                            remote_port_clean = _expand_interface_name(remote_port_clean)

                            link_src = f"{node_id}:{local_port}"
                            link_tgt = f"{remote_node_clean}:{remote_port_clean}"
                            raw_links.append({
                                "link_id": f"{link_src}-to-{link_tgt}",
                                "source": link_src,
                                "target": link_tgt,
                                "type": "NETCONF"
                            })
                            lldp_neighbors_found += 1
                            logger.info(f"  [{node_id}] LLDP: {local_port} → {remote_node_clean}:{remote_port_clean}")

                    oc_success = True
                else:
                    logger.debug(f"  [{node_id}] OpenConfig LLDP returned HTTP {res_oc.status_code}, trying IOS-XE fallback")
            except Exception as oc_err:
                logger.debug(f"  [{node_id}] OpenConfig LLDP exception: {oc_err}, trying IOS-XE fallback")

            # ── Fallback: Vendor-specific Native LLDP ──
            if not oc_success:
                vendor = device.vendor if hasattr(device, 'vendor') and device.vendor else "OTHER"
                
                if vendor == "CISCO":
                    iosxe_url = f"{ODL_BASE}/rests/data/network-topology:network-topology/topology=topology-netconf/node={node_id}/yang-ext:mount/Cisco-IOS-XE-lldp-oper:lldp-entries?content=nonconfig"
                    try:
                        res_ios = requests.get(iosxe_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
                        if res_ios.status_code == 200:
                            raw_nodes.add(node_id)
                            ios_data = res_ios.json()
                            entries = ios_data.get("Cisco-IOS-XE-lldp-oper:lldp-entries", {}).get("lldp-entry", [])
                            for entry in entries:
                                remote_id = entry.get('device-id', '')
                                local_intf = entry.get('local-interface')
                                remote_intf = entry.get('connecting-interface')

                                if remote_id and "openflow" in remote_id:
                                    pass   # keep as-is (e.g. "openflow:1")
                                elif remote_id:
                                    remote_id = remote_id.split('.')[0]

                                if remote_intf:
                                    remote_intf = _expand_interface_name(remote_intf)

                                link_src = f"{node_id}:{local_intf}"
                                link_tgt = f"{remote_id}:{remote_intf}"
                                raw_links.append({
                                    "link_id": f"{link_src}-to-{link_tgt}",
                                    "source": link_src,
                                    "target": link_tgt,
                                    "type": "NETCONF"
                                })
                                lldp_neighbors_found += 1
                                logger.info(f"  [{node_id}] LLDP(IOS-XE): {local_intf} → {remote_id}:{remote_intf}")
                            
                            if lldp_neighbors_found > 0:
                                oc_success = True
                        else:
                            logger.debug(f"  [{node_id}] IOS-XE LLDP returned HTTP {res_ios.status_code}")
                    except Exception as ex:
                        logger.debug(f"  [{node_id}] Failed to fetch IOS-XE LLDP: {ex}")

                elif vendor == "HUAWEI":
                    huawei_url = f"{ODL_BASE}/rests/data/network-topology:network-topology/topology=topology-netconf/node={node_id}/yang-ext:mount/huawei-lldp:lldp?content=nonconfig"
                    try:
                        res_hw = requests.get(huawei_url, auth=AUTH, headers=HEADERS, timeout=TIMEOUT)
                        if res_hw.status_code == 200:
                            raw_nodes.add(node_id)
                            hw_data = res_hw.json()
                            interfaces = hw_data.get("huawei-lldp:lldp", {}).get("lldpInterfaces", {}).get("lldpInterface", [])
                            for intf in interfaces:
                                local_intf = intf.get("ifName")
                                neighbors = intf.get("lldpNeighbor", [])
                                if not neighbors and "lldpNeighbors" in intf:
                                    neighbors = intf.get("lldpNeighbors", {}).get("lldpNeighbor", [])
                                    
                                for neighbor in neighbors:
                                    remote_id = neighbor.get("sysName", "")
                                    remote_intf = neighbor.get("portId", "")

                                    if remote_id and "openflow" not in remote_id:
                                        remote_id = remote_id.split('.')[0]

                                    if remote_intf:
                                        remote_intf = _expand_interface_name(remote_intf)

                                    link_src = f"{node_id}:{local_intf}"
                                    link_tgt = f"{remote_id}:{remote_intf}"
                                    raw_links.append({
                                        "link_id": f"{link_src}-to-{link_tgt}",
                                        "source": link_src,
                                        "target": link_tgt,
                                        "type": "NETCONF"
                                    })
                                    lldp_neighbors_found += 1
                                    logger.info(f"  [{node_id}] LLDP(Huawei): {local_intf} → {remote_id}:{remote_intf}")
                            
                            if lldp_neighbors_found > 0:
                                oc_success = True
                        else:
                            logger.warning(f"  [{node_id}] Huawei LLDP returned HTTP {res_hw.status_code}")
                    except Exception as ex:
                        logger.warning(f"  [{node_id}] Failed to fetch Huawei LLDP: {ex}")
                
                else:
                    logger.debug(f"  [{node_id}] OpenConfig LLDP failed and no specific native LLDP parser implemented for vendor '{vendor}'")

            if lldp_neighbors_found == 0:
                # ยัง add เข้า raw_nodes เพื่อให้ device แสดงใน topology (แม้ไม่มี link)
                raw_nodes.add(node_id)
                logger.info(f"  [{node_id}] No LLDP neighbors found (isolated node)")

    except Exception as e:
        logger.error(f"[1.2] Failed to query NETCONF devices from DB: {e}")

    logger.info(f"[1] Raw data total: {len(raw_nodes)} nodes, {len(raw_links)} links")
    for ln in raw_links:
        logger.info(f"  raw_link: {ln['source']} -> {ln['target']}  (type={ln['type']})")

    # ---------------------------------------------------------
    # 2. เขียนลง DB แบบ Upsert
    # ---------------------------------------------------------
    stats = {"nodes_synced": 0, "interfaces_synced": 0, "links_synced": 0}

    # 2.1) Upsert Nodes (DeviceNetwork) ──────────────────────
    device_id_map: Dict[str, str] = {}   # node_id → device.id (UUID)

    for node_id in raw_nodes:
        if node_id.startswith("openflow:"):
            datapath_id = node_id.split(":")[-1] if ":" in node_id else None

            # ดึงข้อมูลจาก inventory (ถ้ามี)
            inv = of_inventory.get(node_id, {})
            inv_ip = inv.get("ip_address")
            inv_model = inv.get("device_model", "OpenFlow Switch")
            inv_desc = inv.get("description")
            inv_online = inv.get("is_online", False)
            inv_status = "ONLINE" if inv_online else "OFFLINE"

            device = await prisma.devicenetwork.upsert(
                where={"node_id": node_id},
                data={
                    "create": {
                        "node_id": node_id,
                        "device_name": node_id,
                        "serial_number": f"OF-SN-{node_id}",
                        "mac_address": f"OF-MAC-{node_id}",
                        "device_model": inv_model,
                        "type": "SWITCH",
                        "management_protocol": "OPENFLOW",
                        "datapath_id": datapath_id,
                        "vendor": "OTHER",
                        "ip_address": inv_ip,
                        "description": inv_desc,
                        "status": inv_status,
                        "odl_mounted": True,
                        "odl_connection_status": "CONNECTED"
                    },
                    "update": {
                        "datapath_id": datapath_id,
                        "ip_address": inv_ip,
                        "device_model": inv_model,
                        "description": inv_desc,
                        "status": inv_status,
                        "odl_mounted": True,
                        "odl_connection_status": "CONNECTED"
                    }
                }
            )
            device_id_map[node_id] = device.id
            stats["nodes_synced"] += 1
            logger.info(f"[2.1] OF node '{node_id}': status={inv_status}, ip={inv_ip}, model={inv_model}")
        else:
            # NETCONF device ต้องมีอยู่ใน DB ก่อนแล้ว (user สร้างเอง)
            # ห้ามสร้าง dummy device — ถ้าไม่เจอก็ skip
            existing = await prisma.devicenetwork.find_unique(where={"node_id": node_id})
            if existing:
                device_id_map[node_id] = existing.id
                stats["nodes_synced"] += 1
            else:
                logger.warning(f"[2.1] NETCONF node '{node_id}' not found in DB — skipping (no dummy creation)")

    logger.info(f"[2.1] device_id_map keys: {list(device_id_map.keys())}")

    # 2.1.3) Auto-assign local_site_id ให้ OpenFlow switches ──
    # ดู LLDP links ว่า OF switch เชื่อมกับ NETCONF device ไหนที่มี site
    # → สืบทอด local_site_id จาก neighbor NETCONF device
    try:
        # หา NETCONF devices ที่มี local_site_id
        site_devices = await prisma.devicenetwork.find_many(
            where={
                "management_protocol": "NETCONF",
                "local_site_id": {"not": None},
                "node_id": {"not": None},
            }
        )
        # สร้าง map: node_id → local_site_id
        node_to_site: Dict[str, str] = {}
        for sd in site_devices:
            if sd.node_id:
                node_to_site[sd.node_id] = sd.local_site_id

        if node_to_site:
            # ดู raw_links เพื่อหา OF switches ที่เชื่อมกับ NETCONF devices ที่มี site
            of_site_map: Dict[str, str] = {}   # of_node_id → local_site_id
            for ln in raw_links:
                src_parts = ln["source"].rsplit(':', 1)
                tgt_parts = ln["target"].rsplit(':', 1)
                if len(src_parts) != 2 or len(tgt_parts) != 2:
                    continue
                src_node = src_parts[0]
                tgt_node = tgt_parts[0]

                # ถ้า src เป็น OF + tgt เป็น NETCONF ที่มี site
                if src_node.startswith("openflow:") and tgt_node in node_to_site:
                    of_site_map.setdefault(src_node, node_to_site[tgt_node])
                # ถ้า tgt เป็น OF + src เป็น NETCONF ที่มี site
                if tgt_node.startswith("openflow:") and src_node in node_to_site:
                    of_site_map.setdefault(tgt_node, node_to_site[src_node])

            # ถ้ายังไม่ครบ → สืบทอดจาก OF switch ที่ได้ site แล้ว (transitive)
            # วนซ้ำจนกว่าจะไม่มี update
            changed = True
            while changed:
                changed = False
                for ln in raw_links:
                    src_parts = ln["source"].rsplit(':', 1)
                    tgt_parts = ln["target"].rsplit(':', 1)
                    if len(src_parts) != 2 or len(tgt_parts) != 2:
                        continue
                    src_node = src_parts[0]
                    tgt_node = tgt_parts[0]
                    if src_node.startswith("openflow:") and tgt_node.startswith("openflow:"):
                        if src_node in of_site_map and tgt_node not in of_site_map:
                            of_site_map[tgt_node] = of_site_map[src_node]
                            changed = True
                        elif tgt_node in of_site_map and src_node not in of_site_map:
                            of_site_map[src_node] = of_site_map[tgt_node]
                            changed = True

            # Update DB
            for of_node_id, site_id in of_site_map.items():
                of_uuid = device_id_map.get(of_node_id)
                if of_uuid:
                    await prisma.devicenetwork.update(
                        where={"id": of_uuid},
                        data={"local_site_id": site_id}
                    )
                    logger.info(f"[2.1.3] Assigned local_site_id={site_id} to {of_node_id}")
            stats["of_sites_assigned"] = len(of_site_map)
    except Exception as e:
        logger.error(f"[2.1.3] Failed to auto-assign local_site_id to OF switches: {e}")

    # 2.1.5) Build comprehensive node resolver ────────────────
    node_resolver = await _build_node_resolver(prisma, device_id_map)
    logger.info(f"[2.1.5] Node resolver: {len(node_resolver)} entries.  Sample keys: {list(node_resolver.keys())[:20]}")

    # 2.2) Upsert Interfaces (Ports) ─────────────────────────
    interface_id_map: Dict[str, str] = {}   # tp_id → interface.id (UUID)

    unique_tps: Set[str] = set()
    for ln in raw_links:
        unique_tps.add(ln["source"])
        unique_tps.add(ln["target"])
    logger.info(f"[2.2] Unique TPs to process: {sorted(unique_tps)}")

    for tp_id in unique_tps:
        # Parse  "openflow:1:2" → ("openflow:1", "2")
        #        "CSRTH:GigabitEthernet3" → ("CSRTH", "GigabitEthernet3")
        parts = tp_id.rsplit(':', 1)
        if len(parts) != 2:
            logger.warning(f"[2.2] Cannot parse tp_id '{tp_id}' — skipping")
            continue
        node_id_parsed, port_str = parts

        # Resolve node → UUID
        parent_uuid = _resolve_node(node_id_parsed, device_id_map, node_resolver)

        if not parent_uuid:
            # ไม่สร้าง dummy device — ถ้า resolve ไม่ได้ก็ skip interface นี้
            # link ที่อ้าง interface นี้จะถูก skip ใน step 2.3 เอง
            logger.warning(
                f"[2.2] Node '{node_id_parsed}' (tp_id='{tp_id}') not in resolver — skipping. "
                f"Known nodes: {list(device_id_map.keys())}"
            )
            continue

        # Extract port_number (ใช้เฉพาะกับ port ที่เป็นตัวเลขล้วน เช่น OpenFlow port "2")
        port_number = None
        if port_str.isdigit():
            port_number = int(port_str)

        # ดึง port status จาก OF inventory (ถ้ามี)
        of_port_status: Optional[str] = None
        if node_id_parsed.startswith("openflow:"):
            inv = of_inventory.get(node_id_parsed, {})
            port_states = inv.get("port_states", {})
            of_port_status = port_states.get(tp_id)  # tp_id = "openflow:1:2"

        # Upsert interface — ลำดับค้นหา:
        #   1) tp_id (unique)  ← สำคัญที่สุด เพราะ interface อาจถูกสร้างไว้แล้วจาก service อื่น
        #   2) (device_id, name)  ← fallback
        #   3) create ใหม่
        try:
            intf_record = None

            # Strategy 1: หาด้วย tp_id (unique constraint)
            existing_by_tp = await prisma.interface.find_unique(where={"tp_id": tp_id})
            if existing_by_tp:
                intf_record = existing_by_tp
                # ย้ายให้อยู่ถูก device ถ้าจำเป็น
                update_data: Dict[str, Any] = {}
                if existing_by_tp.device_id != parent_uuid:
                    update_data["device_id"] = parent_uuid
                if existing_by_tp.name != port_str:
                    update_data["name"] = port_str
                if port_number is not None and existing_by_tp.port_number != port_number:
                    update_data["port_number"] = port_number
                if of_port_status:
                    update_data["status"] = of_port_status
                if update_data:
                    intf_record = await prisma.interface.update(
                        where={"id": existing_by_tp.id},
                        data=update_data
                    )
                    logger.debug(f"[2.2] Updated existing interface by tp_id: {tp_id}")
            else:
                # Strategy 2: หาด้วย (device_id, name)
                existing_by_name = await prisma.interface.find_first(
                    where={"device_id": parent_uuid, "name": port_str}
                )
                if existing_by_name:
                    intf_record = existing_by_name
                    update_data2: Dict[str, Any] = {}
                    if existing_by_name.tp_id != tp_id:
                        update_data2["tp_id"] = tp_id
                    if port_number is not None and existing_by_name.port_number != port_number:
                        update_data2["port_number"] = port_number
                    if of_port_status:
                        update_data2["status"] = of_port_status
                    if update_data2:
                        intf_record = await prisma.interface.update(
                            where={"id": existing_by_name.id},
                            data=update_data2
                        )
                        logger.debug(f"[2.2] Updated existing interface by (device,name): {tp_id}")
                else:
                    # Strategy 3: สร้างใหม่
                    intf_record = await prisma.interface.create(
                        data={
                            "device_id": parent_uuid,
                            "name": port_str,
                            "tp_id": tp_id,
                            "port_number": port_number,
                            "status": of_port_status or "UP"
                        }
                    )
                    logger.debug(f"[2.2] Created new interface: {tp_id}")

            interface_id_map[tp_id] = intf_record.id
            stats["interfaces_synced"] += 1

        except Exception as e:
            logger.error(f"[2.2] Failed to upsert interface '{tp_id}' (device={parent_uuid}, port={port_str}): {e}")

    logger.info(f"[2.2] interface_id_map: {len(interface_id_map)} entries")

    # 2.3) Upsert Links ──────────────────────────────────────
    # Pre-resolve interface UUIDs + dedup bidirectional (A→B == B→A)
    resolved_links: List[Tuple[str, str, str]] = []  # (src_uuid, tgt_uuid, link_id)
    seen_intf_pairs: Set[Tuple[str, str]] = set()
    skipped_missing = 0
    skipped_dedup = 0

    for ln in raw_links:
        src_uuid = interface_id_map.get(ln["source"])
        tgt_uuid = interface_id_map.get(ln["target"])
        link_id = ln["link_id"]

        if not src_uuid or not tgt_uuid:
            missing = []
            if not src_uuid:
                missing.append(f"source '{ln['source']}'")
            if not tgt_uuid:
                missing.append(f"target '{ln['target']}'")
            logger.warning(f"[2.3] Skip '{link_id}': missing {', '.join(missing)}")
            skipped_missing += 1
            continue

        # Dedup bidirectional (NETCONF: NE40ET→CSR + CSR→NE40ET = same link)
        pair = tuple(sorted([src_uuid, tgt_uuid]))
        if pair in seen_intf_pairs:
            logger.debug(f"[2.3] Dedup bidirectional: {link_id}")
            skipped_dedup += 1
            continue
        seen_intf_pairs.add(pair)
        resolved_links.append((src_uuid, tgt_uuid, link_id))

    if skipped_dedup:
        logger.info(f"[2.3] Deduped {skipped_dedup} bidirectional links")
    if skipped_missing:
        logger.info(f"[2.3] Skipped {skipped_missing} links (missing interfaces)")
    logger.info(f"[2.3] {len(resolved_links)} unique links to upsert")

    active_link_ids: Set[str] = set()
    for src_uuid, tgt_uuid, link_id in resolved_links:
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
            logger.info(f"[2.3] Link OK: {link_id}")
        except Exception as e:
            logger.error(f"[2.3] Failed to upsert link '{link_id}': {e}")

    # =========================================================
    # 3. Cleanup stale Links
    # =========================================================
    try:
        db_links = await prisma.link.find_many()
        stale_link_ids = [
            db_link.id for db_link in db_links
            if not db_link.link_id.startswith("MANUAL:") and db_link.link_id not in active_link_ids
        ]
        if stale_link_ids:
            deleted_links = await prisma.link.delete_many(
                where={"id": {"in": stale_link_ids}}
            )
            stats["links_deleted"] = deleted_links.count
            logger.info(f"[3] Deleted {deleted_links.count} stale links")
    except Exception as e:
        logger.error(f"[3] Failed to clean up stale links: {e}")

    # =========================================================
    # 4. Cleanup stale Dummy Devices (auto-discovered ที่ไม่มี link ใช้แล้ว)
    # =========================================================
    try:
        dummy_devices = await prisma.devicenetwork.find_many(
            where={
                "OR": [
                    {"device_model": "LLDP Neighbor (Auto-discovered)"},
                    {"device_model": "Unknown Neighbor"},
                    {"serial_number": {"startsWith": "DUMMY-SN-"}},
                    {"serial_number": {"startsWith": "LLDP-SN-"}},
                ]
            },
            include={"interfaces": {"include": {"links_source": True, "links_target": True}}}
        )
        stale_dummy_ids = []
        for dd in dummy_devices:
            has_links = False
            for intf in (dd.interfaces or []):
                if (intf.links_source and len(intf.links_source) > 0) or \
                   (intf.links_target and len(intf.links_target) > 0):
                    has_links = True
                    break
            if not has_links:
                stale_dummy_ids.append(dd.id)
                logger.info(f"[4] Removing stale dummy device: {dd.node_id} (model={dd.device_model})")

        if stale_dummy_ids:
            # ลบ interfaces ของ dummy devices ก่อน (cascade อาจไม่ครอบคลุม)
            await prisma.interface.delete_many(where={"device_id": {"in": stale_dummy_ids}})
            deleted_dummies = await prisma.devicenetwork.delete_many(
                where={"id": {"in": stale_dummy_ids}}
            )
            stats["dummy_devices_cleaned"] = deleted_dummies.count
            logger.info(f"[4] Cleaned up {deleted_dummies.count} stale dummy devices")
    except Exception as e:
        logger.error(f"[4] Failed to clean up dummy devices: {e}")

    logger.info(f"=== Topology Sync DONE  stats={stats} ===")
    return stats
