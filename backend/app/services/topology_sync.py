"""
Service for syncing Topology from OpenDaylight to Database (Prisma)
"""
import re
import httpx
from typing import Dict, Any, List, Set, Tuple, Optional
from app.core.config import settings
from app.core.logging import logger
from app.database import get_prisma_client
from app.services.topology_binding_service import get_lldp_binding_map, normalize_chassis_id


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


def _clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_remote_node(node_value: str) -> str:
    node_value = _clean_text(node_value)
    if not node_value:
        return ""
    node_value = node_value.strip('"').strip("'")
    if "openflow" in node_value:
        return node_value
    return node_value.strip()


def _node_alias_candidates(value: str) -> List[str]:
    """Generate conservative hostname aliases for LLDP system-name/device-id matching."""
    base = _normalize_remote_node(value)
    if not base:
        return []

    candidates: List[str] = [base]
    lowered = base.lower()
    if lowered != base:
        candidates.append(lowered)

    # Common CSR/IOS-XE LLDP forms: host.domain, host(extra)
    no_domain = base.split(".", 1)[0].strip()
    if no_domain and no_domain not in candidates:
        candidates.append(no_domain)
    no_paren = no_domain.split("(", 1)[0].strip()
    if no_paren and no_paren not in candidates:
        candidates.append(no_paren)
    if no_paren:
        no_paren_lower = no_paren.lower()
        if no_paren_lower not in candidates:
            candidates.append(no_paren_lower)

    return candidates


def _normalize_mac_key(value: str) -> str:
    """Normalize MAC-like string by removing separators."""
    cleaned = _clean_text(value).lower()
    if not cleaned:
        return ""
    return re.sub(r"[^0-9a-f]", "", cleaned)


def _as_bool(value: Any, default: bool) -> bool:
    """Safe bool parser for env/settings values."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    return default


def _register_port_owner(port_owner_map: Dict[str, Set[str]], node_id: str, port_name: str) -> None:
    """Track which node owns which interface name (normalized) for LLDP fallback resolution."""
    node = _clean_text(node_id)
    port = _expand_interface_name(_clean_text(port_name))
    if not node or not port:
        return
    port_owner_map.setdefault(port, set()).add(node)


def _resolve_remote_by_port_hint(source_node: str, remote_port: str, port_owner_map: Dict[str, Set[str]]) -> str:
    """
    Resolve unknown remote node by remote port name only when it uniquely maps to one node
    (excluding source node). This is a safe fallback for hostname drift.
    """
    port = _expand_interface_name(_clean_text(remote_port))
    if not port:
        return ""

    candidates = set(port_owner_map.get(port, set()))
    src = _clean_text(source_node)
    if src and src in candidates:
        candidates.remove(src)

    if len(candidates) == 1:
        return next(iter(candidates))
    return ""


def _learn_runtime_chassis_map(runtime_map: Dict[str, str], remote_chassis: str, resolved_node: str) -> None:
    """Learn chassis->node mapping from successfully resolved LLDP entries in the current sync run."""
    norm = normalize_chassis_id(_clean_text(remote_chassis))
    node = _clean_text(resolved_node)
    if not norm or not node:
        return

    existing = runtime_map.get(norm)
    if existing and existing != node:
        logger.warning(f"[LLDP-RESOLVE] Runtime chassis conflict: chassis={norm} existing={existing} new={node}; keeping existing")
        return
    runtime_map[norm] = node


# ── Helper: Build a comprehensive node-name → UUID resolver ─
async def _build_node_resolver(prisma, device_id_map: Dict[str, str]) -> Dict[str, str]:
    """
    สร้าง resolver map ที่ครอบคลุมหลายรูปแบบชื่อ → device UUID
    เพื่อให้ LLDP neighbor identity (node_id/MAC/IP) resolve กลับไปหา device ในระบบได้
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
            # Map by node_id only (exact + lower)
            if d.node_id:
                resolver.setdefault(d.node_id, uid)
                resolver.setdefault(d.node_id.lower(), uid)
            # Map by device_name as alias (LLDP system-name is often hostname/display name)
            if getattr(d, "device_name", None):
                dev_name = _clean_text(d.device_name)
                if dev_name:
                    resolver.setdefault(dev_name, uid)
                    resolver.setdefault(dev_name.lower(), uid)
            # Map by MAC address (LLDP chassis-id อาจเป็น MAC)
            if d.mac_address and not d.mac_address.startswith(("OF-MAC-", "DUMMY-MAC-", "LLDP-MAC-")):
                mac_clean = d.mac_address.replace(":", "").replace(".", "").replace("-", "").lower()
                resolver.setdefault(mac_clean, uid)
                resolver.setdefault(d.mac_address.lower(), uid)
                normalized_mac = _normalize_mac_key(d.mac_address)
                if normalized_mac:
                    resolver.setdefault(f"mac:{normalized_mac}", uid)
            # Map by management IP (some LLDP implementations report IP as system/chassis ID)
            if getattr(d, "ip_address", None):
                ip_addr = _clean_text(d.ip_address)
                if ip_addr:
                    resolver.setdefault(ip_addr, uid)
                    resolver.setdefault(ip_addr.lower(), uid)
            # Map by NETCONF host too (some neighbors report mgmt host/IP)
            if getattr(d, "netconf_host", None):
                host = _clean_text(d.netconf_host)
                if host:
                    resolver.setdefault(host, uid)
                    resolver.setdefault(host.lower(), uid)

        # Map by interface MAC address as additional LLDP chassis-id resolver.
        # This is important when hostname changes but LLDP still reports chassis MAC.
        real_device_ids = [d.id for d in all_devices if d.id]
        if real_device_ids:
            iface_rows = await prisma.interface.find_many(
                where={
                    "device_id": {"in": real_device_ids},
                    "mac_address": {"not": None},
                }
            )
            for intf in iface_rows:
                intf_mac = _clean_text(getattr(intf, "mac_address", None))
                intf_dev_id = getattr(intf, "device_id", None)
                if not intf_mac or not intf_dev_id:
                    continue

                resolver.setdefault(intf_mac, intf_dev_id)
                resolver.setdefault(intf_mac.lower(), intf_dev_id)
                intf_mac_compact = _normalize_mac_key(intf_mac)
                if intf_mac_compact:
                    resolver.setdefault(intf_mac_compact, intf_dev_id)
                    resolver.setdefault(f"mac:{intf_mac_compact}", intf_dev_id)
    except Exception as e:
        logger.error(f"Failed to build node resolver: {e}")

    return resolver


def _resolve_node(node_id: str, device_id_map: Dict[str, str], resolver: Dict[str, str]) -> Optional[str]:
    """
    พยายาม resolve node_id → device UUID ด้วยหลายกลยุทธ์:
    1. Direct match ใน device_id_map
    2. Direct match ใน resolver (node_id, MAC, IP)
    3. Case-insensitive
    """
    if node_id in device_id_map:
        return device_id_map[node_id]
    if node_id in resolver:
        return resolver[node_id]

    lower = node_id.lower()
    if lower in resolver:
        return resolver[lower]

    mac_like = _normalize_mac_key(node_id)
    if mac_like:
        if mac_like in resolver:
            return resolver[mac_like]
        if f"mac:{mac_like}" in resolver:
            return resolver[f"mac:{mac_like}"]

    return None


def _split_tp_id(tp_id: str, device_id_map: Dict[str, str], resolver: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """
    Robust TP parser for values like:
      - openflow:1:2
      - CSRTH:GigabitEthernet1
      - NE40TH1:Ethernet1/0/0:0
      - 10.0.0.1:830:GigabitEthernet1
    Chooses split point where node part can be resolved.
    """
    if not tp_id or ":" not in tp_id:
        return None

    split_indexes = [i for i, ch in enumerate(tp_id) if ch == ":"]
    candidates: List[Tuple[str, str]] = []
    for idx in split_indexes:
        node_part = tp_id[:idx]
        port_part = tp_id[idx + 1:]
        if not node_part or not port_part:
            continue
        if _resolve_node(node_part, device_id_map, resolver):
            candidates.append((node_part, port_part))

    if candidates:
        # Prefer the longest resolvable node part to support node IDs containing ':'.
        candidates.sort(key=lambda x: len(x[0]), reverse=True)
        return candidates[0]

    # Fallback to previous behavior.
    parts = tp_id.rsplit(':', 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    return None


def _resolve_remote_node_id(
    remote_name: Optional[str],
    remote_chassis: Optional[str],
    resolver: Dict[str, str],
    uuid_to_node_id: Dict[str, str],
    chassis_binding_map: Dict[str, str],
    known_node_ids: Set[str],
    prefer_chassis_binding: bool = True,
) -> str:
    """
    Resolve LLDP remote endpoint to canonical node_id.
    Priority:
    1) remote_name candidates (exact/alias) if they resolve to a known node
    2) chassis binding map (optional, can be fallback-only)
    3) remote_chassis direct resolve

    This avoids stale chassis bindings overriding an explicit LLDP system-name,
    while still allowing chassis fallback when hostname changes and name resolution fails.
    """
    known_lower_map: Dict[str, str] = {nid.lower(): nid for nid in known_node_ids}
    name_candidates: List[str] = []
    if remote_name:
        name_candidates.extend(_node_alias_candidates(remote_name))

    resolved_by_name = ""
    # First, trust exact known node-id aliases from LLDP system-name/device-id.
    for cand in name_candidates:
        known_hit = known_lower_map.get(cand.lower())
        if known_hit:
            resolved_by_name = known_hit
            break

    # If no exact node_id match, try resolver aliases (device_name, IP, MAC, etc.)
    if not resolved_by_name:
        for cand in name_candidates:
            if not cand:
                continue
            resolved_uuid = _resolve_node(cand, {}, resolver)
            if resolved_uuid and resolved_uuid in uuid_to_node_id:
                resolved_by_name = uuid_to_node_id[resolved_uuid]
                break

    # Always compute chassis-bound candidate; precedence is controlled below.
    chassis_bound = ""
    chassis_norm = normalize_chassis_id(_clean_text(remote_chassis))
    if chassis_norm:
        bound_node = chassis_binding_map.get(chassis_norm)
        if bound_node and bound_node in known_node_ids:
            chassis_bound = bound_node

    if resolved_by_name:
        if chassis_bound and chassis_bound != resolved_by_name:
            logger.warning(
                f"[LLDP-RESOLVE] Name/chassis conflict: remote_name='{_clean_text(remote_name)}' "
                f"resolved='{resolved_by_name}' but chassis maps to '{chassis_bound}'. Using name resolution."
            )
        return resolved_by_name

    # If name didn't resolve, allow chassis fallback (critical when hostname changed).
    if chassis_bound:
        if not prefer_chassis_binding:
            logger.info(
                f"[LLDP-RESOLVE] Using chassis fallback for unresolved remote_name='{_clean_text(remote_name)}' -> '{chassis_bound}'"
            )
        return chassis_bound

    candidates: List[str] = []

    if remote_chassis:
        candidates.append(_clean_text(remote_chassis))

    for cand in candidates:
        if not cand:
            continue
        resolved_uuid = _resolve_node(cand, {}, resolver)
        if resolved_uuid and resolved_uuid in uuid_to_node_id:
            return uuid_to_node_id[resolved_uuid]
    return ""


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
    TIMEOUT = httpx.Timeout(settings.ODL_TIMEOUT_SEC, connect=5.0)
    ODL_BASE = settings.ODL_BASE_URL.rstrip("/")

    # Runtime switches (configurable via app settings/env)
    # Keep defaults compatible with current behavior.
    enable_fallback_resolution = _as_bool(
        getattr(settings, "TOPOLOGY_ENABLE_FALLBACK_RESOLUTION", True),
        True,
    )
    include_debug_stats = _as_bool(
        getattr(settings, "TOPOLOGY_INCLUDE_DEBUG_STATS", True),
        True,
    )
    verbose_sync_logs = _as_bool(
        getattr(settings, "TOPOLOGY_VERBOSE_SYNC_LOGS", False),
        False,
    )

    # Flag: ODL reachable? — ถ้า False จะ skip stale cleanup เพื่อป้องกันลบ topology ตอน ODL down
    odl_reachable = False

    logger.info(f"=== Topology Sync START  (ODL={ODL_BASE}) ===")

    # ---------------------------------------------------------
    # 1. รวบรวมข้อมูลดิบ (Raw Data) จาก ODL
    # ---------------------------------------------------------
    raw_nodes: Set[str] = set()
    raw_links: List[Dict[str, str]] = []
    pending_unresolved_lldp: List[Dict[str, str]] = []
    strict_identity_unresolved = 0
    strict_identity_unresolved_samples: List[str] = []
    port_hint_resolved_count = 0
    port_hint_resolved_samples: List[str] = []

    # Stable resolver for LLDP remote endpoints.
    # Build once so we can map chassis-id/MAC/IP -> canonical node_id during parsing.
    stable_resolver: Dict[str, str] = {}
    uuid_to_node_id: Dict[str, str] = {}
    known_node_ids: Set[str] = set()
    chassis_binding_map: Dict[str, str] = {}
    runtime_chassis_map: Dict[str, str] = {}
    port_owner_map: Dict[str, Set[str]] = {}
    try:
        resolver_devices = await prisma.devicenetwork.find_many(
            where={
                "node_id": {"not": None},
                "NOT": [
                    {"device_model": {"in": ["LLDP Neighbor (Auto-discovered)", "Unknown Neighbor"]}},
                    {"serial_number": {"startsWith": "DUMMY-SN-"}},
                    {"serial_number": {"startsWith": "LLDP-SN-"}},
                ],
            }
        )
        for d in resolver_devices:
            if d.id and d.node_id:
                uuid_to_node_id[d.id] = d.node_id
                known_node_ids.add(d.node_id)

        # Preload interface-name ownership map for fallback remote resolution by port name.
        if enable_fallback_resolution:
            known_device_ids = list(uuid_to_node_id.keys())
            if known_device_ids:
                known_interfaces = await prisma.interface.find_many(
                    where={"device_id": {"in": known_device_ids}}
                )
                for intf in known_interfaces:
                    owner_node = uuid_to_node_id.get(getattr(intf, "device_id", ""))
                    if owner_node:
                        _register_port_owner(port_owner_map, owner_node, getattr(intf, "name", ""))

        stable_resolver = await _build_node_resolver(prisma, {})
        chassis_binding_map = await get_lldp_binding_map(prisma)
    except Exception as e:
        logger.warning(f"[0] Failed to build stable LLDP resolver: {e}")

    # ── Shared async HTTP client สำหรับทุก ODL call ──
    async with httpx.AsyncClient(auth=AUTH, headers=HEADERS, timeout=TIMEOUT) as http:

        # 1.1) ดึง Switch (OpenFlow) ──────────────────────────────
        # ดึงแบบไม่มี ?content=nonconfig เพื่อให้ได้ทั้ง nodes + links ครบถ้วน
        flow_url = f"{ODL_BASE}/rests/data/network-topology:network-topology/topology=flow:1"
        try:
            res_flow = await http.get(flow_url)
            logger.info(f"[1.1] OpenFlow GET {flow_url} → HTTP {res_flow.status_code}")
            odl_reachable = True  # ถ้า request สำเร็จ (แม้ 404) แสดงว่า ODL reachable
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
                res_inv = await http.get(inv_url)
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

                vendor = str(device.vendor).upper() if hasattr(device, 'vendor') and device.vendor else "OTHER"
                lldp_neighbors_found = 0
                oc_success = False

                # ── ลองดึง LLDP ผ่าน OpenConfig ──
                oc_url = f"{ODL_BASE}/rests/data/network-topology:network-topology/topology=topology-netconf/node={node_id}/yang-ext:mount/openconfig-lldp:lldp/interfaces?content=nonconfig"
                try:
                    res_oc = await http.get(oc_url)
                    if res_oc.status_code == 200:
                        raw_nodes.add(node_id)
                        oc_data = res_oc.json()
                        interfaces = oc_data.get("openconfig-lldp:interfaces", {}).get("interface", [])
                        oc_neighbors_before = lldp_neighbors_found

                        for intf in interfaces:
                            local_port = intf.get("name")
                            neighbors = intf.get("neighbors", {}).get("neighbor", [])
                            for neighbor in neighbors:
                                state = neighbor.get("state", {})
                                remote_node = state.get("system-name")
                                remote_chassis = state.get("chassis-id") or neighbor.get("id")
                                remote_port = state.get("port-id")

                                remote_node = _resolve_remote_node_id(
                                    remote_name=remote_node,
                                    remote_chassis=remote_chassis,
                                    resolver=stable_resolver,
                                    uuid_to_node_id=uuid_to_node_id,
                                    chassis_binding_map=chassis_binding_map,
                                    known_node_ids=known_node_ids,
                                    prefer_chassis_binding=(vendor != "CISCO"),
                                )
                                remote_port = _clean_text(remote_port)
                                local_port = _expand_interface_name(_clean_text(local_port))
                                if enable_fallback_resolution:
                                    _register_port_owner(port_owner_map, node_id, local_port)

                                    if (not remote_node) and remote_port and remote_port != "Not Advertised":
                                        hinted_node = _resolve_remote_by_port_hint(node_id, remote_port, port_owner_map)
                                        if hinted_node:
                                            remote_node = hinted_node
                                            port_hint_resolved_count += 1
                                            if len(port_hint_resolved_samples) < 10:
                                                port_hint_resolved_samples.append(f"{node_id}:{local_port} -> {hinted_node}:{_expand_interface_name(remote_port)}")
                                            logger.info(f"  [{node_id}] LLDP(OpenConfig) resolved by port-hint: remote_port={remote_port} -> {hinted_node}")

                                if not remote_node:
                                    strict_identity_unresolved += 1
                                    if len(strict_identity_unresolved_samples) < 10:
                                        strict_identity_unresolved_samples.append(
                                            f"{node_id}:{local_port} remote_name='{_clean_text(state.get('system-name'))}' chassis='{_clean_text(remote_chassis)}'"
                                        )

                                if enable_fallback_resolution and (not remote_node) and local_port and remote_port:
                                    pending_unresolved_lldp.append({
                                        "source_node": node_id,
                                        "source_port": local_port,
                                        "remote_port": remote_port,
                                        "remote_name": _clean_text(state.get("system-name")),
                                        "remote_chassis": _clean_text(remote_chassis),
                                        "vendor": vendor,
                                        "parser": "openconfig",
                                    })

                                if not remote_node or not remote_port or not local_port:
                                    logger.debug(f"  [{node_id}] {local_port}: neighbor missing system-name or port-id, skip")
                                    continue

                                if enable_fallback_resolution:
                                    _learn_runtime_chassis_map(runtime_chassis_map, _clean_text(remote_chassis), remote_node)

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

                        # Fallback to vendor-native parser if OpenConfig is mounted but yields no usable links.
                        if lldp_neighbors_found > oc_neighbors_before:
                            oc_success = True
                        else:
                            logger.debug(f"  [{node_id}] OpenConfig LLDP returned 200 but no valid neighbors, trying vendor fallback")
                    else:
                        logger.debug(f"  [{node_id}] OpenConfig LLDP returned HTTP {res_oc.status_code}, trying IOS-XE fallback")
                except Exception as oc_err:
                    logger.debug(f"  [{node_id}] OpenConfig LLDP exception: {oc_err}, trying IOS-XE fallback")

                # ── Vendor-specific Native LLDP ──
                # For Cisco, run native parser even if OpenConfig succeeded because OC can be partial on CSR.
                if vendor == "CISCO":
                    if oc_success:
                        logger.debug(f"  [{node_id}] OpenConfig LLDP succeeded; querying IOS-XE LLDP for completeness")
                    else:
                        logger.debug(f"  [{node_id}] OpenConfig LLDP unavailable/partial; querying IOS-XE LLDP")

                    iosxe_url = f"{ODL_BASE}/rests/data/network-topology:network-topology/topology=topology-netconf/node={node_id}/yang-ext:mount/Cisco-IOS-XE-lldp-oper:lldp-entries?content=nonconfig"
                    try:
                        res_ios = await http.get(iosxe_url)
                        if res_ios.status_code == 200:
                            raw_nodes.add(node_id)
                            ios_data = res_ios.json()
                            entries = ios_data.get("Cisco-IOS-XE-lldp-oper:lldp-entries", {}).get("lldp-entry", [])
                            for entry in entries:
                                remote_id = _clean_text(entry.get('device-id') or entry.get('system-name') or entry.get('system-name-detail') or "")
                                remote_mgmt = _clean_text(
                                    entry.get('management-address')
                                    or entry.get('mgmt-address')
                                    or entry.get('ip-address')
                                    or ""
                                )
                                remote_chassis = _clean_text(
                                    entry.get('chassis-id')
                                    or entry.get('chassis-id-detail')
                                    or entry.get('chassis-id-string')
                                    or entry.get('chassis-id-mac')
                                    or ""
                                )
                                local_intf = _expand_interface_name(_clean_text(
                                    entry.get('local-interface')
                                    or entry.get('local-intf-name')
                                    or entry.get('local-intf')
                                    or entry.get('local-port-id')
                                    or ""
                                ))
                                if enable_fallback_resolution:
                                    _register_port_owner(port_owner_map, node_id, local_intf)
                                remote_intf = _clean_text(
                                    entry.get('connecting-interface')
                                    or entry.get('port-id-detail')
                                    or entry.get('port-id')
                                    or entry.get('port-description')
                                    or ""
                                )

                                resolved_remote_id = _resolve_remote_node_id(
                                    remote_name=remote_id or remote_mgmt,
                                    remote_chassis=remote_chassis,
                                    resolver=stable_resolver,
                                    uuid_to_node_id=uuid_to_node_id,
                                    chassis_binding_map=chassis_binding_map,
                                    known_node_ids=known_node_ids,
                                    prefer_chassis_binding=False,
                                )
                                if (not resolved_remote_id) and remote_mgmt and remote_mgmt != remote_id:
                                    resolved_remote_id = _resolve_remote_node_id(
                                        remote_name=remote_mgmt,
                                        remote_chassis=remote_chassis,
                                        resolver=stable_resolver,
                                        uuid_to_node_id=uuid_to_node_id,
                                        chassis_binding_map=chassis_binding_map,
                                        known_node_ids=known_node_ids,
                                        prefer_chassis_binding=False,
                                    )
                                if remote_intf:
                                    remote_intf = _expand_interface_name(remote_intf)

                                if enable_fallback_resolution and (not resolved_remote_id) and remote_intf:
                                    hinted_node = _resolve_remote_by_port_hint(node_id, remote_intf, port_owner_map)
                                    if hinted_node:
                                        resolved_remote_id = hinted_node
                                        port_hint_resolved_count += 1
                                        if len(port_hint_resolved_samples) < 10:
                                            port_hint_resolved_samples.append(f"{node_id}:{local_intf} -> {hinted_node}:{remote_intf}")
                                        logger.info(f"  [{node_id}] LLDP(IOS-XE) resolved by port-hint: remote_port={remote_intf} -> {hinted_node}")

                                if not resolved_remote_id:
                                    strict_identity_unresolved += 1
                                    if len(strict_identity_unresolved_samples) < 10:
                                        strict_identity_unresolved_samples.append(
                                            f"{node_id}:{local_intf} remote_name='{_clean_text(entry.get('device-id'))}' mgmt='{remote_mgmt}' chassis='{remote_chassis}'"
                                        )

                                if enable_fallback_resolution and (not resolved_remote_id) and local_intf and remote_intf:
                                    pending_unresolved_lldp.append({
                                        "source_node": node_id,
                                        "source_port": local_intf,
                                        "remote_port": remote_intf,
                                        "remote_name": _clean_text(entry.get("device-id") or entry.get("system-name") or entry.get("system-name-detail") or ""),
                                        "remote_chassis": remote_chassis,
                                        "vendor": vendor,
                                        "parser": "ios-xe",
                                    })

                                if not resolved_remote_id or not local_intf or not remote_intf:
                                    logger.debug(f"  [{node_id}] LLDP(IOS-XE) skipped invalid entry: local='{local_intf}' remote='{resolved_remote_id}' port='{remote_intf}'")
                                    continue

                                if enable_fallback_resolution:
                                    _learn_runtime_chassis_map(runtime_chassis_map, remote_chassis, resolved_remote_id)

                                link_src = f"{node_id}:{local_intf}"
                                link_tgt = f"{resolved_remote_id}:{remote_intf}"
                                raw_links.append({
                                    "link_id": f"{link_src}-to-{link_tgt}",
                                    "source": link_src,
                                    "target": link_tgt,
                                    "type": "NETCONF"
                                })
                                lldp_neighbors_found += 1
                                logger.info(f"  [{node_id}] LLDP(IOS-XE): {local_intf} → {resolved_remote_id}:{remote_intf}")

                            if lldp_neighbors_found > 0:
                                oc_success = True
                        else:
                            logger.debug(f"  [{node_id}] IOS-XE LLDP returned HTTP {res_ios.status_code}")
                    except Exception as ex:
                        logger.debug(f"  [{node_id}] Failed to fetch IOS-XE LLDP: {ex}")

                elif (not oc_success) and vendor == "HUAWEI":
                    huawei_url = f"{ODL_BASE}/rests/data/network-topology:network-topology/topology=topology-netconf/node={node_id}/yang-ext:mount/huawei-lldp:lldp?content=nonconfig"
                    try:
                        res_hw = await http.get(huawei_url)
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
                                    remote_name = _clean_text(neighbor.get("sysName") or "")
                                    remote_mgmt = _clean_text(
                                        neighbor.get("managementAddress")
                                        or neighbor.get("management-address")
                                        or neighbor.get("mgmtAddress")
                                        or neighbor.get("mgmt-address")
                                        or neighbor.get("sysManagementAddress")
                                        or ""
                                    )
                                    remote_chassis = _clean_text(neighbor.get("chassisId") or "")
                                    remote_intf = _clean_text(neighbor.get("portId") or neighbor.get("portDescription") or "")
                                    local_intf_clean = _expand_interface_name(_clean_text(local_intf))
                                    if enable_fallback_resolution:
                                        _register_port_owner(port_owner_map, node_id, local_intf_clean)

                                    remote_id = _resolve_remote_node_id(
                                        remote_name=remote_name or remote_mgmt,
                                        remote_chassis=remote_chassis,
                                        resolver=stable_resolver,
                                        uuid_to_node_id=uuid_to_node_id,
                                        chassis_binding_map=chassis_binding_map,
                                        known_node_ids=known_node_ids,
                                        prefer_chassis_binding=True,
                                    )
                                    if (not remote_id) and remote_mgmt and remote_mgmt != remote_name:
                                        remote_id = _resolve_remote_node_id(
                                            remote_name=remote_mgmt,
                                            remote_chassis=remote_chassis,
                                            resolver=stable_resolver,
                                            uuid_to_node_id=uuid_to_node_id,
                                            chassis_binding_map=chassis_binding_map,
                                            known_node_ids=known_node_ids,
                                            prefer_chassis_binding=True,
                                        )
                                    if remote_intf:
                                        remote_intf = _expand_interface_name(remote_intf)

                                    if enable_fallback_resolution and (not remote_id) and remote_intf:
                                        hinted_node = _resolve_remote_by_port_hint(node_id, remote_intf, port_owner_map)
                                        if hinted_node:
                                            remote_id = hinted_node
                                            port_hint_resolved_count += 1
                                            if len(port_hint_resolved_samples) < 10:
                                                port_hint_resolved_samples.append(f"{node_id}:{local_intf_clean} -> {hinted_node}:{remote_intf}")
                                            logger.info(f"  [{node_id}] LLDP(Huawei) resolved by port-hint: remote_port={remote_intf} -> {hinted_node}")

                                    if not remote_id:
                                        strict_identity_unresolved += 1
                                        if len(strict_identity_unresolved_samples) < 10:
                                            strict_identity_unresolved_samples.append(
                                                f"{node_id}:{local_intf_clean} remote_name='{remote_name}' mgmt='{remote_mgmt}' chassis='{remote_chassis}'"
                                            )

                                    if enable_fallback_resolution and (not remote_id) and local_intf_clean and remote_intf:
                                        pending_unresolved_lldp.append({
                                            "source_node": node_id,
                                            "source_port": local_intf_clean,
                                            "remote_port": remote_intf,
                                            "remote_name": remote_name or remote_mgmt,
                                            "remote_chassis": remote_chassis,
                                            "vendor": vendor,
                                            "parser": "huawei",
                                        })

                                    if not remote_id or not local_intf_clean or not remote_intf:
                                        logger.debug(f"  [{node_id}] LLDP(Huawei) skipped invalid entry: local='{local_intf_clean}' remote='{remote_id}' port='{remote_intf}'")
                                        continue

                                    if enable_fallback_resolution:
                                        _learn_runtime_chassis_map(runtime_chassis_map, remote_chassis, remote_id)

                                    link_src = f"{node_id}:{local_intf_clean}"
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

                elif not oc_success:
                    logger.debug(f"  [{node_id}] OpenConfig LLDP failed and no specific native LLDP parser implemented for vendor '{vendor}'")

                if lldp_neighbors_found == 0:
                    # ยัง add เข้า raw_nodes เพื่อให้ device แสดงใน topology (แม้ไม่มี link)
                    raw_nodes.add(node_id)
                    logger.info(f"  [{node_id}] No LLDP neighbors found (isolated node)")

        except Exception as e:
            logger.error(f"[1.2] Failed to query NETCONF devices from DB: {e}")

    # 1.2.8) Second-pass unresolved resolution by finalized port-owner map.
    # This removes device-order dependency (e.g., CSR parsed before NE owner port is learned).
    second_pass_port_hint_resolved = 0
    second_pass_port_hint_samples: List[str] = []
    if enable_fallback_resolution and pending_unresolved_lldp:
        existing_directed_raw: Set[Tuple[str, str]] = {
            (ln["source"], ln["target"]) for ln in raw_links if ln.get("type") == "NETCONF"
        }

        for obs in pending_unresolved_lldp:
            src_node = _clean_text(obs.get("source_node"))
            src_port = _expand_interface_name(_clean_text(obs.get("source_port")))
            remote_port = _expand_interface_name(_clean_text(obs.get("remote_port")))
            if not src_node or not src_port or not remote_port:
                continue
            if remote_port == "Not Advertised":
                continue

            hinted_node = _resolve_remote_by_port_hint(src_node, remote_port, port_owner_map)
            if not hinted_node:
                chassis_norm = normalize_chassis_id(_clean_text(obs.get("remote_chassis")))
                if chassis_norm:
                    hinted_node = runtime_chassis_map.get(chassis_norm) or chassis_binding_map.get(chassis_norm, "")
                    if hinted_node == src_node:
                        hinted_node = ""
            if not hinted_node:
                continue

            src_tp = f"{src_node}:{src_port}"
            tgt_tp = f"{hinted_node}:{remote_port}"
            pair = (src_tp, tgt_tp)
            if pair in existing_directed_raw:
                continue

            raw_links.append({
                "link_id": f"{src_tp}-to-{tgt_tp}",
                "source": src_tp,
                "target": tgt_tp,
                "type": "NETCONF",
            })
            existing_directed_raw.add(pair)
            second_pass_port_hint_resolved += 1
            if len(second_pass_port_hint_samples) < 10:
                second_pass_port_hint_samples.append(f"{src_tp} -> {tgt_tp}")

        if second_pass_port_hint_resolved:
            logger.info(f"[1.2.8] Resolved {second_pass_port_hint_resolved} pending LLDP links by second-pass port-hint")
            logger.info(f"[1.2.8] Samples: {second_pass_port_hint_samples}")

    # 1.2.9) Infer unresolved LLDP links by reciprocal port observations.
    # This recovers links when both sides see each other but remote hostnames don't map to DB node_id.
    inferred_unresolved_links = 0
    inferred_unresolved_samples: List[str] = []
    if enable_fallback_resolution and pending_unresolved_lldp:
        existing_tps: Set[str] = set()
        for ln in raw_links:
            if ln.get("type") != "NETCONF":
                continue
            existing_tps.add(ln["source"])
            existing_tps.add(ln["target"])

        candidate_map: Dict[int, List[int]] = {}
        for i, p in enumerate(pending_unresolved_lldp):
            pi_src_node = p.get("source_node", "")
            pi_src_port = p.get("source_port", "")
            pi_remote_port = p.get("remote_port", "")
            cands: List[int] = []
            if not pi_src_node or not pi_src_port or not pi_remote_port:
                candidate_map[i] = cands
                continue

            for j, q in enumerate(pending_unresolved_lldp):
                if i == j:
                    continue
                q_src_node = q.get("source_node", "")
                q_src_port = q.get("source_port", "")
                q_remote_port = q.get("remote_port", "")
                if not q_src_node or not q_src_port or not q_remote_port:
                    continue
                if pi_src_node == q_src_node:
                    continue
                if pi_src_port == q_remote_port and pi_remote_port == q_src_port:
                    cands.append(j)
            candidate_map[i] = cands

        used_idx: Set[int] = set()
        for i, cands in candidate_map.items():
            if i in used_idx or len(cands) != 1:
                continue
            j = cands[0]
            if j in used_idx:
                continue

            back_cands = candidate_map.get(j, [])
            if len(back_cands) != 1 or back_cands[0] != i:
                continue

            p = pending_unresolved_lldp[i]
            q = pending_unresolved_lldp[j]
            src_tp = f"{p['source_node']}:{p['source_port']}"
            tgt_tp = f"{q['source_node']}:{q['source_port']}"
            if src_tp in existing_tps or tgt_tp in existing_tps:
                continue

            raw_links.append({
                "link_id": f"{src_tp}-to-{tgt_tp}",
                "source": src_tp,
                "target": tgt_tp,
                "type": "NETCONF",
            })
            raw_links.append({
                "link_id": f"{tgt_tp}-to-{src_tp}",
                "source": tgt_tp,
                "target": src_tp,
                "type": "NETCONF",
            })
            existing_tps.add(src_tp)
            existing_tps.add(tgt_tp)
            used_idx.add(i)
            used_idx.add(j)
            inferred_unresolved_links += 1
            if len(inferred_unresolved_samples) < 10:
                inferred_unresolved_samples.append(f"{src_tp} <-> {tgt_tp}")

        if inferred_unresolved_links:
            logger.info(f"[1.2.9] Inferred {inferred_unresolved_links} reciprocal unresolved LLDP links")
            logger.info(f"[1.2.9] Samples: {inferred_unresolved_samples}")
    else:
        inferred_unresolved_samples = []

    # 1.2.10) Infer unresolved observations by matching against already-resolved links.
    # Example: resolved A:Gi3 -> B:Eth1/0/2 and unresolved B:Eth1/0/2 -> ?:Gi3
    # => infer B:Eth1/0/2 -> A:Gi3.
    inferred_from_resolved_links = 0
    inferred_from_resolved_samples: List[str] = []
    if enable_fallback_resolution and pending_unresolved_lldp and raw_links:
        netconf_existing = [ln for ln in raw_links if ln.get("type") == "NETCONF"]
        existing_directed = {(ln["source"], ln["target"]) for ln in netconf_existing}

        for obs in pending_unresolved_lldp:
            obs_src_tp = f"{obs.get('source_node', '')}:{obs.get('source_port', '')}"
            obs_remote_port = _expand_interface_name(_clean_text(obs.get("remote_port")))
            if not obs_src_tp or not obs_remote_port:
                continue

            # Find candidate resolved links ending at this observed source TP
            # with source port equal to observed remote_port.
            candidates: List[str] = []  # candidate remote tp_id
            for ln in netconf_existing:
                if ln.get("target") != obs_src_tp:
                    continue
                src_parts = ln.get("source", "").rsplit(":", 1)
                if len(src_parts) != 2:
                    continue
                ln_src_port = _expand_interface_name(_clean_text(src_parts[1]))
                if ln_src_port == obs_remote_port:
                    candidates.append(ln["source"])

            # Ambiguous or no match -> skip (safety first).
            if len(candidates) != 1:
                continue

            inferred_target_tp = candidates[0]
            inferred_pair = (obs_src_tp, inferred_target_tp)
            if inferred_pair in existing_directed:
                continue

            raw_links.append({
                "link_id": f"{obs_src_tp}-to-{inferred_target_tp}",
                "source": obs_src_tp,
                "target": inferred_target_tp,
                "type": "NETCONF",
            })
            existing_directed.add(inferred_pair)
            inferred_from_resolved_links += 1
            if len(inferred_from_resolved_samples) < 10:
                inferred_from_resolved_samples.append(f"{obs_src_tp} -> {inferred_target_tp}")

        if inferred_from_resolved_links:
            logger.info(f"[1.2.10] Inferred {inferred_from_resolved_links} reverse links from unresolved observations")
            logger.info(f"[1.2.10] Samples: {inferred_from_resolved_samples}")

    logger.info(f"[1] Raw data total: {len(raw_nodes)} nodes, {len(raw_links)} links")
    if verbose_sync_logs:
        for ln in raw_links:
            logger.info(f"  raw_link: {ln['source']} -> {ln['target']}  (type={ln['type']})")

    # 1.3) NETCONF link quality policy
    # Default: keep unilateral NETCONF links to avoid hiding real edges when only one side reports.
    # Can be overridden by setting TOPOLOGY_KEEP_UNILATERAL_NETCONF=false.
    keep_unilateral_setting = getattr(settings, "TOPOLOGY_KEEP_UNILATERAL_NETCONF", True)
    keep_unilateral_netconf = _as_bool(keep_unilateral_setting, True)
    if raw_links:
        raw_link_pairs = {(ln["source"], ln["target"]) for ln in raw_links}
        seen_directed: Set[Tuple[str, str]] = set()
        filtered_raw_links: List[Dict[str, str]] = []
        unilateral_netconf_observed = 0
        unilateral_netconf_dropped = 0
        unilateral_netconf_samples: List[str] = []
        duplicate_directed_dropped = 0
        for ln in raw_links:
            src_tgt = (ln["source"], ln["target"])
            if src_tgt in seen_directed:
                duplicate_directed_dropped += 1
                continue

            seen_directed.add(src_tgt)

            if ln.get("type") == "NETCONF" and (ln["target"], ln["source"]) not in raw_link_pairs:
                unilateral_netconf_observed += 1
                if len(unilateral_netconf_samples) < 10:
                    unilateral_netconf_samples.append(f"{ln['source']} -> {ln['target']}")
                if keep_unilateral_netconf:
                    logger.info(f"[1.3] Unilateral NETCONF LLDP observed (kept): {ln['source']} -> {ln['target']}")
                    filtered_raw_links.append(ln)
                else:
                    unilateral_netconf_dropped += 1
                    logger.info(f"[1.3] Drop unilateral NETCONF LLDP link: {ln['source']} -> {ln['target']}")
                continue

            filtered_raw_links.append(ln)

        if unilateral_netconf_observed:
            if keep_unilateral_netconf:
                logger.info(f"[1.3] Observed {unilateral_netconf_observed} unilateral NETCONF links")
            else:
                logger.info(f"[1.3] Dropped {unilateral_netconf_dropped} unilateral NETCONF links")
        if duplicate_directed_dropped:
            logger.info(f"[1.3] Dropped {duplicate_directed_dropped} duplicate directed links")
        unilateral_netconf_dropped_count = unilateral_netconf_dropped
        unilateral_netconf_observed_count = unilateral_netconf_observed
        unilateral_netconf_samples_count = unilateral_netconf_samples
        raw_links = filtered_raw_links
    else:
        unilateral_netconf_dropped_count = 0
        unilateral_netconf_observed_count = 0
        unilateral_netconf_samples_count = []

    netconf_conflict_skipped = 0
    netconf_conflict_samples: List[str] = []

    # 1.4) NETCONF endpoint conflict resolution
    # A physical interface should map to at most one active LLDP neighbor in the same snapshot.
    # If conflicts exist, prefer reciprocal-confirmed links (A:pa -> B:pb and B:pb -> A:pa).
    if raw_links:
        reverse_pairs = {(ln["source"], ln["target"]) for ln in raw_links if ln.get("type") == "NETCONF"}
        netconf_links = [ln for ln in raw_links if ln.get("type") == "NETCONF"]
        other_links = [ln for ln in raw_links if ln.get("type") != "NETCONF"]

        def _netconf_score(link: Dict[str, str]) -> int:
            reverse_exists = (link["target"], link["source"]) in reverse_pairs
            return 1 if reverse_exists else 0

        # Deterministic order: reciprocal first, then stable by link_id.
        netconf_links_sorted = sorted(
            netconf_links,
            key=lambda ln: (-_netconf_score(ln), ln.get("link_id", "")),
        )

        used_tps: Set[str] = set()
        selected_netconf: List[Dict[str, str]] = []
        for ln in netconf_links_sorted:
            src_tp = ln["source"]
            tgt_tp = ln["target"]
            if src_tp in used_tps or tgt_tp in used_tps:
                netconf_conflict_skipped += 1
                if len(netconf_conflict_samples) < 10:
                    netconf_conflict_samples.append(f"{src_tp} -> {tgt_tp}")
                if verbose_sync_logs:
                    logger.info(f"[1.4] Drop conflict link: {src_tp} -> {tgt_tp}")
                continue
            used_tps.add(src_tp)
            used_tps.add(tgt_tp)
            selected_netconf.append(ln)
            if verbose_sync_logs:
                logger.info(f"[1.4] Keep NETCONF link: {src_tp} -> {tgt_tp}")

        if netconf_conflict_skipped:
            logger.info(f"[1.4] Skipped {netconf_conflict_skipped} NETCONF port-conflict links")
            logger.info(f"[1.4] Samples: {netconf_conflict_samples}")

        raw_links = other_links + selected_netconf

    # ---------------------------------------------------------
    # 2. เขียนลง DB แบบ Upsert
    # ---------------------------------------------------------
    stats = {
        "nodes_synced": 0,
        "interfaces_synced": 0,
        "links_synced": 0,
        "raw_nodes": len(raw_nodes),
        "raw_links": len(raw_links),
        "unique_tps": 0,
        "resolved_links": 0,
        "skipped_missing_links": 0,
        "skipped_dedup_links": 0,
        "netconf_port_conflicts_skipped": 0,
        "netconf_port_conflict_samples": [],
        "unilateral_netconf_dropped": 0,
        "unilateral_netconf_observed": 0,
        "unilateral_netconf_samples": [],
        "strict_identity_unresolved": 0,
        "strict_identity_unresolved_samples": [],
        "port_hint_resolved": 0,
        "port_hint_resolved_samples": [],
        "port_hint_second_pass_resolved": 0,
        "port_hint_second_pass_samples": [],
        "unresolved_lldp_inferred_links": 0,
        "unresolved_lldp_inferred_samples": [],
        "unresolved_lldp_inferred_from_resolved_links": 0,
        "unresolved_lldp_inferred_from_resolved_samples": [],
        "unresolved_nodes": [],
        "unresolved_tps": [],
    }
    stats["netconf_port_conflicts_skipped"] = netconf_conflict_skipped
    stats["netconf_port_conflict_samples"] = netconf_conflict_samples
    stats["unilateral_netconf_dropped"] = unilateral_netconf_dropped_count
    stats["unilateral_netconf_observed"] = unilateral_netconf_observed_count
    stats["unilateral_netconf_samples"] = unilateral_netconf_samples_count
    stats["strict_identity_unresolved"] = strict_identity_unresolved
    stats["strict_identity_unresolved_samples"] = strict_identity_unresolved_samples
    stats["port_hint_resolved"] = port_hint_resolved_count
    stats["port_hint_resolved_samples"] = port_hint_resolved_samples
    stats["port_hint_second_pass_resolved"] = second_pass_port_hint_resolved
    stats["port_hint_second_pass_samples"] = second_pass_port_hint_samples
    stats["unresolved_lldp_inferred_links"] = inferred_unresolved_links
    stats["unresolved_lldp_inferred_samples"] = inferred_unresolved_samples
    stats["unresolved_lldp_inferred_from_resolved_links"] = inferred_from_resolved_links
    stats["unresolved_lldp_inferred_from_resolved_samples"] = inferred_from_resolved_samples

    if not include_debug_stats:
        stats["netconf_port_conflict_samples"] = []
        stats["unilateral_netconf_samples"] = []
        stats["strict_identity_unresolved_samples"] = []
        stats["port_hint_resolved_samples"] = []
        stats["port_hint_second_pass_samples"] = []
        stats["unresolved_lldp_inferred_samples"] = []
        stats["unresolved_lldp_inferred_from_resolved_samples"] = []

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
    stats["unique_tps"] = len(unique_tps)
    logger.info(f"[2.2] Unique TPs to process: {sorted(unique_tps)}")
    unresolved_nodes: Set[str] = set()
    unresolved_tps: List[str] = []

    for tp_id in unique_tps:
        # Parse  "openflow:1:2" → ("openflow:1", "2")
        #        "CSRTH:GigabitEthernet3" → ("CSRTH", "GigabitEthernet3")
        parsed_tp = _split_tp_id(tp_id, device_id_map, node_resolver)
        if not parsed_tp:
            logger.warning(f"[2.2] Cannot parse tp_id '{tp_id}' — skipping")
            continue
        node_id_parsed, port_str = parsed_tp

        # Resolve node → UUID
        parent_uuid = _resolve_node(node_id_parsed, device_id_map, node_resolver)

        if not parent_uuid:
            # ไม่สร้าง dummy device — ถ้า resolve ไม่ได้ก็ skip interface นี้
            # link ที่อ้าง interface นี้จะถูก skip ใน step 2.3 เอง
            logger.warning(
                f"[2.2] Node '{node_id_parsed}' (tp_id='{tp_id}') not in resolver — skipping. "
                f"Known nodes: {list(device_id_map.keys())}"
            )
            unresolved_nodes.add(node_id_parsed)
            if len(unresolved_tps) < 20:
                unresolved_tps.append(tp_id)
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
    stats["resolved_links"] = len(resolved_links)
    stats["skipped_missing_links"] = skipped_missing
    stats["skipped_dedup_links"] = skipped_dedup
    stats["unresolved_nodes"] = sorted(unresolved_nodes)
    stats["unresolved_tps"] = unresolved_tps

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
    # 3. Cleanup stale Links (ONLY if ODL was reachable)
    # =========================================================
    if not odl_reachable:
        logger.warning("[3] ODL unreachable — skipping stale link/device cleanup to preserve topology")
    else:
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
