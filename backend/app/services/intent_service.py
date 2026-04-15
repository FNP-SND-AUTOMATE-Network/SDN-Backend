"""
Intent Service - Core service for handling Intent requests

Refactored from Strategy Resolver to Deterministic Driver Factory Pattern:
- No fallback mechanism (reduces latency)
- Post-error diagnosis via DeviceManager (capability check on failure)
- Direct driver selection based on vendor
- All write operations use PATCH method

Terminology:
-----------
- node_id: ODL topology-netconf identifier (URL-safe)
           Used in both API requests and database
- device_id: Database UUID (internal, not in API)

Flow:
-----
1. API receives: { "intent": "show.interface", "node_id": "CSR1" }
2. Query DeviceNetwork WHERE node_id = 'CSR1'
3. DriverFactory selects native driver based on vendor (no fallback)
4. Driver builds RESTCONF request
5. Send to ODL via client
6. Normalize response if needed
7. Return unified response
"""
import asyncio
import ipaddress
from typing import Dict, Any, Optional
from app.schemas.intent import (
    IntentRequest, IntentResponse,
    IntentBulkRequest, IntentBulkResponse,
    BulkIntentItemResult, BulkIntentStatus
)
from app.services.device_profile_service_db import DeviceProfileService
from app.services.driver_factory import DriverFactory
from app.clients.odl_restconf_client import OdlRestconfClient
from app.normalizers.interface import InterfaceNormalizer
from app.normalizers.system import SystemNormalizer
from app.normalizers.routing import RoutingNormalizer, InterfaceBriefNormalizer, OspfNormalizer
from app.normalizers.dhcp import DhcpNormalizer
from app.normalizers.config import ConfigNormalizer
from app.core.errors import OdlRequestError, UnsupportedIntent, DeviceNotMounted
from app.core.intent_registry import IntentRegistry, Intents, IntentCategory
from app.core.logging import logger
from app.services.device_manager import DeviceManager

# Interface Drivers
from app.drivers.cisco.ios_xe.interface import CiscoInterfaceDriver
from app.drivers.huawei.vrp8.interface import HuaweiInterfaceDriver

# System Drivers
from app.drivers.cisco.ios_xe.system import CiscoSystemDriver
from app.drivers.huawei.vrp8.system import HuaweiSystemDriver

# Routing Drivers
from app.drivers.cisco.ios_xe.routing import CiscoRoutingDriver
from app.drivers.huawei.vrp8.routing import HuaweiRoutingDriver


# DHCP Drivers
from app.drivers.huawei.vrp8.dhcp import HuaweiDhcpDriver
from app.drivers.cisco.ios_xe.dhcp import CiscoDhcpDriver

# Device Driver (mount/unmount)
from app.drivers.device import DeviceDriver


class IntentService:
    """
    Main service for handling Intent-based requests
    
    Architecture: Deterministic Driver Factory Pattern
    - No fallback mechanism for lower latency
    - Driver selected directly based on device vendor
    
    Terminology Note:
        - req.node_id = database 'node_id' = ODL node identifier
        - Used directly in ODL RESTCONF paths
    
    Flow:
    1. Validate intent exists in registry
    2. Get device profile (lookup by node_id)
    3. DriverFactory selects native driver (deterministic, no fallback)
    4. Driver builds RESTCONF request
    5. Send to ODL via client
    6. Normalize response if needed
    7. Return unified response
    """

    
    def __init__(self):
        self.device_profiles = DeviceProfileService()
        self.client = OdlRestconfClient()
        
        # Normalizers
        self.interface_normalizer = InterfaceNormalizer()
        self.system_normalizer = SystemNormalizer()
        self.dhcp_normalizer = DhcpNormalizer()
        self.config_normalizer = ConfigNormalizer()
        
        # Device driver (mount/unmount)
        self.device_driver = DeviceDriver()
    
    def _get_driver(self, intent: str, driver_name: str, os_type: Optional[str] = None):
        """Get appropriate driver based on intent category using DriverFactory"""
        intent_def = IntentRegistry.get(intent)
        if not intent_def:
            raise UnsupportedIntent(intent)
        
        # Select category
        category = intent_def.category
        
        # Special handling for SHOW category which maps to specific drivers
        if category == IntentCategory.SHOW:
            if intent in [Intents.SHOW.INTERFACE, Intents.SHOW.INTERFACES]:
                category = IntentCategory.INTERFACE
            elif intent in [Intents.SHOW.RUNNING_CONFIG, Intents.SHOW.VERSION]:
                category = IntentCategory.SYSTEM
            elif intent in [Intents.SHOW.IP_ROUTE, Intents.SHOW.IP_INTERFACE_BRIEF,
                           Intents.SHOW.OSPF_NEIGHBORS, Intents.SHOW.OSPF_DATABASE]:
                category = IntentCategory.ROUTING
            elif intent == Intents.SHOW.DHCP_POOLS:
                category = IntentCategory.DHCP
            else:
                 category = IntentCategory.INTERFACE
        
        # Use DriverFactory to get the driver
        return DriverFactory.get_driver(
            node_id="unknown", # We don't have node_id here easily, but it's for logging only
            vendor=driver_name,
            os_type=os_type,
            category=category
        )
    
    async def handle(self, req: IntentRequest) -> IntentResponse:
        """Handle incoming intent request"""
        
        # Step 1: Validate intent exists
        intent_def = IntentRegistry.get(req.intent)
        if not intent_def:
            raise UnsupportedIntent(req.intent)
        
        # Step 2: Validate required params
        missing = IntentRegistry.validate_params(req.intent, req.params)
        if missing:
            raise UnsupportedIntent(f"Missing params: {', '.join(missing)}")
        
        # Step 3: Get device profile
        device = await self.device_profiles.get(req.node_id)
        
        # OpenFlow devices are managed via RESTful endpoints, not intents
        if getattr(device, "management_protocol", "NETCONF") == "OPENFLOW":
            raise UnsupportedIntent(
                f"OpenFlow devices do not use the intent system. "
                f"Please use the RESTful flow endpoints instead: "
                f"POST /api/v1/nbi/devices/{req.node_id}/flows/..."
            )
        
        # Step 4: Check if device is mounted and connected (NETCONF only)
        mount_status = await self.device_profiles.check_mount_status(req.node_id)
        if not mount_status.get("ready_for_intent"):
            connection_status = mount_status.get("connection_status", "unknown")
            is_mounted = mount_status.get("mounted", False)
            
            if not is_mounted:
                raise DeviceNotMounted(
                    f"Device '{req.node_id}' is not mounted in ODL. "
                    f"Please mount the device first using POST /api/v1/nbi/devices/{req.node_id}/mount"
                )
            elif connection_status == "connecting":
                raise DeviceNotMounted(
                    f"Device '{req.node_id}' is still connecting. "
                    f"Current status: {connection_status}. Please wait and try again."
                )
            else:
                raise DeviceNotMounted(
                    f"Device '{req.node_id}' is not connected. "
                    f"Current status: {connection_status}. Please check device connectivity."
                )
                
        # Special handling for DEVICE category (mount/unmount/status etc)
        if intent_def.category == IntentCategory.DEVICE:
            return await self._handle_device_intent(req)
        
        # Step 5: Get driver directly from factory (deterministic - no fallback)
        os_type = device.os_type     # Use OsType (required: "CISCO_IOS_XE", "HUAWEI_VRP")
        driver_name = os_type or device.vendor  # os_type เป็น primary key สำหรับ driver + normalizer
    
        # Guard write-intents with live ODL preflight to avoid schema-flapping reconnect loops.
        # DB mount state can be stale while ODL session/schema is re-negotiating.
        if not intent_def.is_read_only:
            await self._preflight_write_intent(req.node_id, req.intent, driver_name)
        
        logger.info(f"Intent: {req.intent}, Device: {req.node_id}, "
                   f"Driver: {driver_name}, OS: {os_type} (deterministic)")
        
        # Step 6: Execute with native driver (no fallback mechanism)
        return await self._execute(req, device, driver_name, os_type)

    async def _preflight_write_intent(self, node_id: str, intent: str, vendor: str) -> None:
        """
        Live preflight for write intents:
        - Ensure ODL currently reports the node as connected
        - Ensure required modules for this intent are available (if mapped)

        This prevents sending config during schema/session flaps that can trigger
        repeated reconnect and growing unavailable-capabilities.
        """
        diagnosis = await self._diagnose_odl_error(
            node_id=node_id,
            intent=intent,
            vendor=vendor,
            odl_error="preflight-check",
        )

        # If diagnosis is unavailable, do not hard-block to avoid false negatives.
        if not diagnosis:
            return

        conn = str(diagnosis.get("connection_status", "unknown")).lower()
        if conn != "connected":
            raise DeviceNotMounted(
                f"Device '{node_id}' is not ready for write intent '{intent}' "
                f"(ODL connection_status={conn}). Please wait for stable connected state and retry."
            )

        missing_modules = diagnosis.get("missing_modules") or []
        required_modules = diagnosis.get("required_modules") or []
        if required_modules and missing_modules:
            preview = ", ".join(missing_modules[:6])
            if len(missing_modules) > 6:
                preview += f" (+{len(missing_modules) - 6} more)"

            raise OdlRequestError(
                status_code=409,
                message=(
                    f"Schema not ready for intent '{intent}' on '{node_id}'. "
                    f"Missing required module(s): {preview}. "
                    "Please remount and wait until schema sync stabilizes before retrying."
                ),
                details={
                    "node_id": node_id,
                    "intent": intent,
                    "missing_modules": missing_modules,
                    "required_modules": required_modules,
                    "diagnosis": diagnosis,
                },
            )

    async def _handle_device_intent(self, req: IntentRequest) -> IntentResponse:
        """
        Handle device management intents (status/list)
        These don't require device profile lookup
        
        Note: mount/unmount removed - use dedicated REST endpoints:
            POST /api/v1/nbi/devices/{node_id}/mount
            DELETE /api/v1/nbi/devices/{node_id}/mount
        """
        node_id = req.node_id  # Use node_id directly for ODL
        
        if req.intent == Intents.DEVICE.STATUS:
            spec = self.device_driver.build_get_status(node_id)
        elif req.intent == Intents.DEVICE.LIST:
            spec = self.device_driver.build_list_devices()
        else:
            raise UnsupportedIntent(f"Unknown device intent: {req.intent}")
        
        logger.info(f"Device Intent: {req.intent}, Node: {node_id}")
        logger.debug(f"RequestSpec: {spec.method} {spec.path}")
        
        # Send to ODL
        raw = await self.client.send(spec)
        
        # Normalize device status response
        result = self._normalize_device_response(req.intent, raw)
        
        return IntentResponse(
            success=True,
            intent=req.intent,
            node_id=req.node_id,
            driver_used="device",
            result=result
        )
    
    def _normalize_device_response(self, intent: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize device management responses"""
        if intent == Intents.DEVICE.STATUS:
            # Extract connection status from response
            node = raw.get("node", [{}])[0] if "node" in raw else raw
            return {
                "node_id": node.get("node-id", ""),
                "connection_status": node.get("netconf-node-topology:connection-status", "unknown"),
                "host": node.get("netconf-node-topology:host", ""),
                "port": node.get("netconf-node-topology:port", 830),
                "available_capabilities": node.get("netconf-node-topology:available-capabilities", {}).get("available-capability", [])
            }
        
        if intent == Intents.DEVICE.LIST:
            # Extract list of devices
            topology = raw.get("network-topology:topology", [{}])[0] if "network-topology:topology" in raw else raw
            nodes = topology.get("node", [])
            devices = []
            for n in nodes:
                devices.append({
                    "node_id": n.get("node-id", ""),
                    "connection_status": n.get("netconf-node-topology:connection-status", "unknown"),
                    "host": n.get("netconf-node-topology:host", ""),
                    "port": n.get("netconf-node-topology:port", 830),
                })
            return {"devices": devices, "total": len(devices)}
        
        return raw

    # ── Shared DeviceManager singleton (lazy init) ──
    _device_manager: Optional[DeviceManager] = None

    @classmethod
    def _get_device_manager(cls) -> DeviceManager:
        """Lazy-init DeviceManager singleton"""
        if cls._device_manager is None:
            cls._device_manager = DeviceManager()
        return cls._device_manager

    async def _execute(self, req: IntentRequest, device, driver_name: str, os_type: Optional[str] = None) -> IntentResponse:
        """Execute intent with specific driver"""
        driver = self._get_driver(req.intent, driver_name, os_type)
        
        if not driver:
            raise UnsupportedIntent(req.intent, os_type=os_type or driver_name)
        
        # ── Huawei-specific pre-flight checks ──
        # ก่อน set_ipv4 บน Huawei: ตรวจ existing IP และ subnet conflict
        is_huawei = driver_name and "HUAWEI" in driver_name.upper()
        if req.intent == Intents.INTERFACE.SET_IPV4 and is_huawei:
            await self._pre_check_huawei_set_ipv4(req.node_id, device, req.params)
        
        # ── Cisco-specific pre-flight checks ──
        is_cisco = driver_name and "CISCO" in driver_name.upper()
        if req.intent.startswith("routing.ospf") and is_cisco:
            await self._pre_check_cisco_version(req.node_id, req.params)
        if req.intent == Intents.ROUTING.OSPF_DISABLE and is_cisco:
            await self._pre_cleanup_cisco_ospf_interfaces(req.node_id, req.params)
        
        # Build RESTCONF request spec
        spec = driver.build(device, req.intent, req.params)
        logger.debug(f"RequestSpec: {spec.method} {spec.path}")

        try:
            # Send to ODL
            raw = await self.client.send(spec)
        except OdlRequestError as e:
            recovered = False
            if (
                is_cisco
                and req.intent == Intents.ROUTING.OSPF_ADD_NETWORK_INTERFACE
                and self._is_cisco_ospf_process_missing_error(e)
            ):
                logger.warning(
                    f"[AutoRecover] {req.node_id}: OSPF process not found for interface binding. "
                    "Enabling process then retrying intent."
                )
                await self._auto_enable_cisco_ospf_process(
                    device=device,
                    node_id=req.node_id,
                    driver_name=driver_name,
                    os_type=os_type,
                    params=req.params,
                )
                # Retry the original intent once after creating process.
                spec = driver.build(device, req.intent, req.params)
                raw = await self.client.send(spec)
                recovered = True

            if not recovered:
                # Huawei mount is connected but schema/module context is not ready.
                # Return an actionable message instead of generic payload diagnosis.
                if is_huawei and self._is_huawei_module_lookup_error(e):
                    raise OdlRequestError(
                        status_code=409,
                        message=(
                            f"Huawei module context is not ready on {req.node_id}. "
                            "ODL cannot resolve required module (huawei-ifm/huawei-ip). "
                            "Please remount with schemaless=false and wait until schema sync completes, then retry."
                        ),
                        details={
                            "node_id": req.node_id,
                            "intent": req.intent,
                            "original_error": str(e),
                            "hint": "Wait for full schema sync or force-remount with schema enabled",
                        },
                    ) from e

                # ── Idempotent DELETE: ถ้า DELETE แล้วได้ 500/404 with empty body
                # หมายความว่า resource ไม่มีอยู่แล้ว (NETCONF data-missing)
                # ถือเป็น success เพราะ state ที่ต้องการคือ "ไม่มี resource นั้น"
                status_code = getattr(e, 'status_code', 0)
                # OdlRequestError เก็บ details ใน e.detail (FastAPI HTTPException)
                # structure: e.detail = {"message": "...", "details": {"url": ..., "body": "..."}}
                odl_body = ""
                detail = getattr(e, 'detail', {})
                if isinstance(detail, dict):
                    inner = detail.get('details', {})
                    if isinstance(inner, dict):
                        odl_body = inner.get('body', '')
                if spec.method == "DELETE" and status_code in (404, 500) and not odl_body:
                    logger.info(
                        f"[Idempotent DELETE] {req.intent} on {req.node_id}: "
                        f"resource not found (already deleted). Treating as success."
                    )
                    raw = {"ok": True, "message": "Resource already absent (idempotent delete)"}
                else:
                    # ── Post-error diagnosis (non-blocking) ──
                    diagnosis = await self._diagnose_odl_error(
                        node_id=req.node_id,
                        intent=req.intent,
                        vendor=driver_name,
                        odl_error=str(e),
                    )
                    # Re-raise with enhanced error message
                    enhanced_msg = f"ODL request failed: {e}"
                    if diagnosis and diagnosis.get("suggestion"):
                        enhanced_msg += f" | Diagnosis: {diagnosis['suggestion']}"
                    raise OdlRequestError(
                        status_code=status_code or 502,
                        message=enhanced_msg,
                        details={
                            "original_error": str(e),
                            "diagnosis": diagnosis,
                        },
                    ) from e

        # ── Huawei post-step: encap VLAN หลังสร้าง sub-interface ──
        if req.intent == Intents.INTERFACE.CREATE_SUBINTERFACE and is_huawei:
            await self._post_huawei_encap_vlan(req.node_id, req.params)

        # ── Huawei post-step: disable IPv6 หลังจากลบ address ──
        if req.intent == Intents.INTERFACE.REMOVE_IPV6 and is_huawei:
            await self._post_huawei_disable_ipv6(req.node_id, req.params)

        # Normalize response if needed (pass node_id for routing normalizers)
        result = self._normalize_response(req.intent, driver_name, raw, req.node_id, req.params)

        return IntentResponse(
            success=True,
            intent=req.intent,
            node_id=req.node_id,
            driver_used=driver_name,
            result=result
        )

    @staticmethod
    def _is_huawei_module_lookup_error(err: Exception) -> bool:
        """Detect ODL unknown-element/module-lookup errors for Huawei YANG modules."""
        text = str(err).lower()
        return (
            "failed to lookup for module with name" in text
            and ("huawei-ifm" in text or "huawei-ip" in text)
        ) or (
            "unknown-element" in text
            and ("huawei-ifm" in text or "huawei-ip" in text)
        )

    async def _post_huawei_encap_vlan(
        self, node_id: str, params: Dict[str, Any]
    ) -> None:
        """
        Post-step: ตั้ง VLAN encapsulation บน sub-interface ที่เพิ่งสร้าง

        ใช้ huawei-ethernet:ethernet/ethSubIfs/ethSubIf YANG path
        เพื่อ set dot1q VLAN tag (flowType=VlanType)
        """
        import urllib.parse
        from app.builders.odl_paths import odl_mount_base
        from app.schemas.request_spec import RequestSpec

        ifname = params.get("interface", "")
        vlan_id = params.get("vlan_id")
        if not ifname or vlan_id is None:
            return

        vlan_id_str = str(vlan_id)
        sub_ifname = f"{ifname}.{vlan_id_str}"  # e.g. Ethernet1/0/2.50
        encoded_sub = urllib.parse.quote(sub_ifname, safe='')
        mount = odl_mount_base(node_id)

        encap_spec = RequestSpec(
            method="PATCH",
            datastore="config",
            path=f"{mount}/huawei-ethernet:ethernet/ethSubIfs/ethSubIf={encoded_sub}",
            payload={
                "huawei-ethernet:ethSubIf": [{
                    "ifName": sub_ifname,
                    "vlanTypeVid": int(vlan_id),
                    "flowType": "VlanType"
                }]
            },
            headers={
                "Content-Type": "application/yang-data+json",
                "Accept": "application/yang-data+json"
            },
            intent="post_step.encap_vlan",
            driver="huawei",
        )

        logger.info(
            f"[PostStep] Setting VLAN encap {vlan_id} on {sub_ifname} ({node_id})"
        )
        await self.client.send(encap_spec)
        logger.info(
            f"[PostStep] VLAN encap {vlan_id} set successfully on {sub_ifname}"
        )

    async def _post_huawei_disable_ipv6(
        self, node_id: str, params: Dict[str, Any]
    ) -> None:
        """
        Post-step: ปิด IPv6 (enableFlag: false) บน interface หลังจากลบ address ออก
        """
        import urllib.parse
        from app.builders.odl_paths import odl_mount_base
        from app.schemas.request_spec import RequestSpec

        ifname = params.get("interface", "")
        if not ifname:
            return

        encoded_ifname = urllib.parse.quote(ifname, safe='')
        mount = odl_mount_base(node_id)

        disable_spec = RequestSpec(
            method="PATCH",
            datastore="config",
            path=f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}/ipv6Config",
            payload={
                "ipv6Config": {
                    "enableFlag": False
                }
            },
            headers={
                "Content-Type": "application/yang-data+json",
                "Accept": "application/yang-data+json"
            },
            intent="post_step.disable_ipv6",
            driver="huawei",
        )

        logger.info(
            f"[PostStep] Disabling IPv6 on {ifname} ({node_id})"
        )
        await self.client.send(disable_spec)
        logger.info(
            f"[PostStep] IPv6 disabled successfully on {ifname}"
        )

    async def _diagnose_odl_error(
        self, node_id: str, intent: str, vendor: str, odl_error: str
    ) -> Optional[Dict[str, Any]]:
        """
        Run DeviceManager diagnosis (async, non-blocking)
        """
        try:
            dm = self._get_device_manager()
            # diagnose_error is now async — no need for to_thread()
            diagnosis = await dm.diagnose_error(node_id, intent, vendor, odl_error)
            if diagnosis and diagnosis.get("diagnosed"):
                logger.info(
                    f"[Diagnosis] {node_id}/{intent}: {diagnosis.get('suggestion', '')}"
                )
            return diagnosis
        except Exception as diag_err:
            logger.warning(f"[Diagnosis] Failed for {node_id}: {diag_err}")
            return None

    async def _pre_check_cisco_version(
        self, node_id: str, params: Dict[str, Any]
    ) -> None:
        """Fetch Cisco IOS-XE version and inject it into params"""
        from app.builders.odl_paths import odl_mount_base
        from app.schemas.request_spec import RequestSpec
        
        mount = odl_mount_base(node_id)
        get_spec = RequestSpec(
            method="GET",
            datastore="operational",
            path=f"{mount}/Cisco-IOS-XE-native:native/version",
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent="pre_check.get_version",
            driver="cisco",
        )
        try:
            logger.info(f"[PreCheck] Fetching OS version for Cisco device {node_id}")
            resp = await self.client.send(get_spec)
            raw_version = resp.get("Cisco-IOS-XE-native:version", "16.9")
            if isinstance(raw_version, dict):
                version_str = str(raw_version.get("version", "16.9"))
            else:
                version_str = str(raw_version or "16.9")
        except Exception as e:
            logger.warning(f"[PreCheck] Failed to fetch Cisco version for {node_id}, defaulting to 16.9: {e}")
            version_str = "16.9"
            
        logger.info(f"[PreCheck] Cisco device {node_id} version detected as: {version_str}")
        params["device_version"] = version_str

    @staticmethod
    def _is_cisco_ospf_process_missing_error(err: Exception) -> bool:
        """Detect IOS-XE error when interface OSPF is configured before process exists."""
        text = str(err).lower()
        return "configure router ospf first" in text and "bad-element" in text

    async def _auto_enable_cisco_ospf_process(
        self,
        device,
        node_id: str,
        driver_name: str,
        os_type: Optional[str],
        params: Dict[str, Any],
    ) -> None:
        """Issue routing.ospf.enable using current process_id before retrying interface bind."""
        process_id = params.get("process_id")
        if process_id is None:
            raise OdlRequestError(
                status_code=400,
                message="process_id is required for OSPF auto-recovery",
                details={"node_id": node_id, "intent": Intents.ROUTING.OSPF_ENABLE},
            )

        driver = self._get_driver(Intents.ROUTING.OSPF_ENABLE, driver_name, os_type)
        if not driver:
            raise OdlRequestError(
                status_code=500,
                message="Unable to resolve Cisco routing driver for OSPF auto-recovery",
                details={"node_id": node_id, "intent": Intents.ROUTING.OSPF_ENABLE},
            )

        enable_params: Dict[str, Any] = {"process_id": process_id}
        if "device_version" in params:
            enable_params["device_version"] = params["device_version"]

        enable_spec = driver.build(device, Intents.ROUTING.OSPF_ENABLE, enable_params)
        await self.client.send(enable_spec)
        logger.info(
            f"[AutoRecover] OSPF process {process_id} enabled on {node_id}; retrying interface OSPF intent"
        )

    async def _pre_cleanup_cisco_ospf_interfaces(
        self, node_id: str, params: Dict[str, Any]
    ) -> None:
        """
        Before disabling OSPF process, remove interface-level OSPF references
        that still point to the same process-id.

        Without this, IOS-XE can reject the transaction with:
        "configure router ospf first <bad-element>id</bad-element>".
        """
        import urllib.parse
        from app.builders.odl_paths import odl_mount_base
        from app.schemas.request_spec import RequestSpec

        process_id = params.get("process_id")
        if process_id is None:
            return

        try:
            process_id_int = int(process_id)
        except Exception:
            logger.warning(
                f"[PreCheck] Invalid OSPF process_id for cleanup: {process_id}"
            )
            return

        mount = odl_mount_base(node_id)
        get_spec = RequestSpec(
            method="GET",
            datastore="config",
            path=f"{mount}/Cisco-IOS-XE-native:native/interface",
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent="pre_check.ospf_disable.get_interfaces",
            driver="cisco",
        )

        try:
            iface_resp = await self.client.send(get_spec)
        except Exception as e:
            logger.warning(
                f"[PreCheck] Failed to fetch interface config for OSPF cleanup on {node_id}: {e}"
            )
            return

        iface_root = iface_resp.get("Cisco-IOS-XE-native:interface") or iface_resp.get("interface")
        if not isinstance(iface_root, dict):
            return

        cleaned = 0
        for if_type, if_entries in iface_root.items():
            if not isinstance(if_entries, list):
                continue

            for if_entry in if_entries:
                if not isinstance(if_entry, dict):
                    continue

                if_name = str(if_entry.get("name", "") or "")
                ip_cfg = if_entry.get("ip", {})
                if not if_name or not isinstance(ip_cfg, dict):
                    continue

                if not self._cisco_interface_has_ospf_process(ip_cfg, process_id_int):
                    continue

                encoded_if_name = urllib.parse.quote(if_name, safe="")
                delete_paths = [
                    (
                        f"{mount}/Cisco-IOS-XE-native:native/interface/{if_type}={encoded_if_name}"
                        f"/ip/Cisco-IOS-XE-ospf:router-ospf/ospf/process-id={process_id_int}"
                    ),
                    (
                        f"{mount}/Cisco-IOS-XE-native:native/interface/{if_type}={encoded_if_name}"
                        f"/ip/Cisco-IOS-XE-ospf:ospf={process_id_int}"
                    ),
                ]

                for delete_path in delete_paths:
                    del_spec = RequestSpec(
                        method="DELETE",
                        datastore="config",
                        path=delete_path,
                        payload=None,
                        headers={"Accept": "application/yang-data+json"},
                        intent="pre_check.ospf_disable.cleanup_interface",
                        driver="cisco",
                    )
                    try:
                        await self.client.send(del_spec)
                    except OdlRequestError as e:
                        # Ignore already-absent path during cleanup.
                        if getattr(e, "status_code", 0) in (404, 500):
                            continue
                        raise

                cleaned += 1

        if cleaned:
            logger.info(
                f"[PreCheck] Removed OSPF process {process_id_int} from {cleaned} interface(s) on {node_id}"
            )

    @staticmethod
    def _cisco_interface_has_ospf_process(ip_cfg: Dict[str, Any], process_id: int) -> bool:
        """Detect whether an interface IP config references the given OSPF process-id."""
        # IOS-XE 17+ shape
        router_ospf = ip_cfg.get("Cisco-IOS-XE-ospf:router-ospf") or ip_cfg.get("router-ospf")
        if isinstance(router_ospf, dict):
            ospf = router_ospf.get("ospf")
            if isinstance(ospf, dict):
                process_list = ospf.get("process-id", [])
                if isinstance(process_list, dict):
                    process_list = [process_list]
                if isinstance(process_list, list):
                    for item in process_list:
                        if isinstance(item, dict) and int(item.get("id", -1)) == process_id:
                            return True

        # IOS-XE 16.x shape
        legacy_ospf = ip_cfg.get("Cisco-IOS-XE-ospf:ospf") or ip_cfg.get("ospf", [])
        if isinstance(legacy_ospf, dict):
            legacy_ospf = [legacy_ospf]
        if isinstance(legacy_ospf, list):
            for item in legacy_ospf:
                if isinstance(item, dict) and int(item.get("id", -1)) == process_id:
                    return True

        return False

    async def _pre_check_huawei_set_ipv4(
        self, node_id: str, device, params: Dict[str, Any]
    ) -> None:
        """
        Pre-flight check สำหรับ Huawei interface.set_ipv4

        Case 1: Interface มี IP อยู่แล้ว → DELETE ก่อน แล้วค่อย SET ใหม่
        Case 2: IP ใหม่ซ้ำ subnet กับ interface อื่น → raise error ชัดเจน
        """
        import urllib.parse
        from app.builders.odl_paths import odl_mount_base
        from app.schemas.request_spec import RequestSpec

        ifname = params.get("interface", "")
        new_ip = params.get("ip", "")
        new_prefix = params.get("prefix") or params.get("mask", "")
        mount = odl_mount_base(node_id)
        encoded_ifname = urllib.parse.quote(ifname, safe='')

        # ── Step 1: GET current interface config ──
        logger.info(f"[PreCheck] GET interface {ifname} on {node_id}")
        get_spec = RequestSpec(
            method="GET",
            datastore="config",
            path=f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}",
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent="pre_check.get_interface",
            driver="huawei",
        )
        try:
            iface_data = await self.client.send(get_spec)
        except OdlRequestError:
            iface_data = {}

        # ตรวจว่ามี IP อยู่ใน interface นี้หรือไม่
        existing_ip = None
        existing_mask = None
        try:
            iface_list = (
                iface_data.get("huawei-ifm:interface", [{}])
                if isinstance(iface_data.get("huawei-ifm:interface"), list)
                else [iface_data.get("huawei-ifm:interface", {})]
            )
            addr_list = (
                iface_list[0]
                .get("ipv4Config", {})
                .get("am4CfgAddrs", {})
                .get("am4CfgAddr", [])
            )
            if addr_list:
                existing_ip = addr_list[0].get("ifIpAddr")
                existing_mask = addr_list[0].get("subnetMask")
        except Exception:
            pass

        # Case 1: มี IP อยู่แล้ว → DELETE ก่อน
        if existing_ip:
            logger.info(
                f"[PreCheck] Interface {ifname} has existing IP {existing_ip}/{existing_mask}, "
                f"deleting before set new IP {new_ip}"
            )
            del_spec = RequestSpec(
                method="DELETE",
                datastore="config",
                path=f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}/ipv4Config/am4CfgAddrs",
                payload=None,
                headers={"Accept": "application/yang-data+json"},
                intent="pre_check.delete_ipv4",
                driver="huawei",
            )
            try:
                await self.client.send(del_spec)
                logger.info(f"[PreCheck] Existing IP {existing_ip} removed from {ifname}")
            except OdlRequestError as e:
                # 500/404 body ว่าง = resource ไม่มีอยู่แล้ว ถือว่าสำเร็จ
                status_code = getattr(e, 'status_code', 0)
                detail = getattr(e, 'detail', {})
                odl_body = ""
                if isinstance(detail, dict):
                    inner = detail.get('details', {})
                    if isinstance(inner, dict):
                        odl_body = inner.get('body', '')
                if status_code in (404, 500) and not odl_body:
                    pass  # already deleted, continue
                else:
                    raise

        # ── Step 2: GET all interfaces → ตรวจ subnet conflict ──
        logger.info(f"[PreCheck] Checking subnet conflict for {new_ip} on {node_id}")
        all_spec = RequestSpec(
            method="GET",
            datastore="config",
            path=f"{mount}/huawei-ifm:ifm/interfaces",
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent="pre_check.get_interfaces",
            driver="huawei",
        )
        try:
            all_data = await self.client.send(all_spec)
        except OdlRequestError:
            all_data = {}

        # แปลง new IP เป็น network object สำหรับเทียบ
        try:
            # รองรับทั้ง prefix (24) และ mask (255.255.255.0)
            if str(new_prefix).isdigit():
                new_network = ipaddress.IPv4Network(f"{new_ip}/{new_prefix}", strict=False)
            else:
                new_network = ipaddress.IPv4Network(f"{new_ip}/{new_prefix}", strict=False)
        except ValueError:
            logger.warning(f"[PreCheck] Cannot parse new IP {new_ip}/{new_prefix}, skipping subnet check")
            return

        # วน loop ทุก interface เพื่อหา subnet ซ้ำ
        all_ifaces = (
            all_data.get("huawei-ifm:interfaces", {}).get("interface", [])
        )
        for iface in all_ifaces:
            other_name = iface.get("ifName", "")
            # ข้ามตัวเอง
            if other_name == ifname:
                continue
            try:
                other_addrs = (
                    iface.get("ipv4Config", {})
                    .get("am4CfgAddrs", {})
                    .get("am4CfgAddr", [])
                )
                for addr in other_addrs:
                    other_ip = addr.get("ifIpAddr", "")
                    other_mask = addr.get("subnetMask", "")
                    if not other_ip or not other_mask:
                        continue
                    other_network = ipaddress.IPv4Network(f"{other_ip}/{other_mask}", strict=False)
                    if new_network.overlaps(other_network):
                        raise OdlRequestError(
                            status_code=409,
                            message=(
                                f"IP conflict: {new_ip}/{new_prefix} is in the same subnet as "
                                f"{other_name} ({other_ip}/{other_mask}). "
                                f"Huawei VRP does not allow two interfaces in the same subnet."
                            ),
                            details={
                                "conflicting_interface": other_name,
                                "conflicting_ip": other_ip,
                                "conflicting_mask": other_mask,
                                "requested_ip": new_ip,
                                "requested_prefix": str(new_prefix),
                            }
                        )
            except OdlRequestError:
                raise
            except Exception:
                continue

        logger.info(f"[PreCheck] No subnet conflict found for {new_ip}/{new_prefix} on {node_id}")
    
    def _normalize_response(self, intent: str, driver_name: str, raw: Dict[str, Any], device_id: str = "", params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Normalize response based on intent type"""
        
        # Check if intent needs normalization
        intent_def = IntentRegistry.get(intent)
        if not intent_def:
            return raw
        
        if not params:
            params = {}
        
        # Interface normalizations
        if intent == Intents.SHOW.INTERFACE:
            return self.interface_normalizer.normalize_show_interface(driver_name, raw)
        
        if intent == Intents.SHOW.INTERFACES:
            return self.interface_normalizer.normalize_show_interfaces(driver_name, raw)
        
        # System normalizations
        if intent == Intents.SHOW.VERSION:
            return self.system_normalizer.normalize_show_version(driver_name, raw)
        
        if intent == Intents.SHOW.RUNNING_CONFIG:
            return self.system_normalizer.normalize_show_running_config(driver_name, raw)
        
        # Routing normalizations
        if intent == Intents.SHOW.IP_ROUTE:
            return RoutingNormalizer.normalize(raw, device_id, driver_name).model_dump()
        
        if intent == Intents.SHOW.IP_INTERFACE_BRIEF:
            return InterfaceBriefNormalizer.normalize(raw, device_id, driver_name).model_dump()
        
        # OSPF normalizations
        if intent == Intents.SHOW.OSPF_NEIGHBORS:
            return OspfNormalizer.normalize_neighbors(raw, device_id, driver_name).model_dump()
        
        if intent == Intents.SHOW.OSPF_DATABASE:
            return OspfNormalizer.normalize_database(raw, device_id, driver_name).model_dump()
        
        
        # DHCP normalization
        if intent == Intents.SHOW.DHCP_POOLS:
            return self.dhcp_normalizer.normalize_show_dhcp_pools(driver_name, raw)
        
        # Config Normalization (Write Operations)
        if intent_def.category != IntentCategory.SHOW and intent_def.category != IntentCategory.DEVICE:
             return self.config_normalizer.normalize(intent, driver_name, raw, params)
        
        return raw
    
    def get_supported_intents(self) -> Dict[str, Any]:
        """Get list of all supported intents (for API discovery)"""
        return IntentRegistry.get_supported_intents()

    async def handle_bulk(self, req: IntentBulkRequest) -> IntentBulkResponse:
        """
        Handle bulk intent request using Fail-Fast pattern.
        
        Iterates through intents sequentially. On first failure:
        - Records the failed intent
        - Marks ALL remaining intents as CANCELLED
        - Returns immediately with partial results
        
        This prevents pushing inconsistent configurations to the device.
        """
        results: list[BulkIntentItemResult] = []
        succeeded = 0
        failed = 0
        cancelled = 0
        abort = False

        for idx, intent_req in enumerate(req.intents):
            if abort:
                # Mark remaining intents as CANCELLED
                results.append(BulkIntentItemResult(
                    index=idx,
                    status=BulkIntentStatus.CANCELLED,
                    intent=intent_req.intent,
                    node_id=intent_req.node_id,
                    error="Cancelled due to previous failure (Fail-Fast)"
                ))
                cancelled += 1
                continue

            try:
                # Execute via the existing single-intent handler
                response = await self.handle(intent_req)

                results.append(BulkIntentItemResult(
                    index=idx,
                    status=BulkIntentStatus.SUCCESS,
                    intent=intent_req.intent,
                    node_id=intent_req.node_id,
                    driver_used=response.driver_used,
                    result=response.result
                ))
                succeeded += 1

            except Exception as e:
                # Record the failure and activate Fail-Fast abort
                error_msg = str(e)
                # Extract detail from HTTPException if available
                detail = getattr(e, 'detail', None)
                if detail and isinstance(detail, dict):
                    error_msg = detail.get('message', error_msg)

                results.append(BulkIntentItemResult(
                    index=idx,
                    status=BulkIntentStatus.FAILED,
                    intent=intent_req.intent,
                    node_id=intent_req.node_id,
                    error=error_msg
                ))
                failed += 1
                abort = True  # Trigger Fail-Fast

                logger.warning(
                    f"[BulkIntent] Fail-Fast triggered at index {idx}: "
                    f"intent={intent_req.intent}, node={intent_req.node_id}, error={error_msg}"
                )

        all_success = failed == 0
        logger.info(
            f"[BulkIntent] Completed: {succeeded} succeeded, {failed} failed, "
            f"{cancelled} cancelled out of {len(req.intents)} total"
        )

        return IntentBulkResponse(
            success=all_success,
            total=len(req.intents),
            succeeded=succeeded,
            failed=failed,
            cancelled=cancelled,
            results=results
        )
