"""
Intent Service - Core service for handling Intent requests

Refactored from Strategy Resolver to Deterministic Driver Factory Pattern:
- No fallback mechanism (reduces latency)
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
from typing import Dict, Any
from app.schemas.intent import IntentRequest, IntentResponse
from app.services.device_profile_service_db import DeviceProfileService
from app.services.driver_factory import DriverFactory
from app.clients.odl_restconf_client import OdlRestconfClient
from app.normalizers.interface import InterfaceNormalizer
from app.normalizers.system import SystemNormalizer
from app.normalizers.routing import RoutingNormalizer, InterfaceBriefNormalizer, OspfNormalizer
from app.normalizers.vlan import VlanNormalizer
from app.normalizers.dhcp import DhcpNormalizer
from app.core.errors import OdlRequestError, UnsupportedIntent, DeviceNotMounted
from app.core.intent_registry import IntentRegistry, Intents, IntentCategory
from app.core.logging import logger

# Interface Drivers
from app.drivers.openconfig.interface import OpenConfigInterfaceDriver
from app.drivers.cisco.interface import CiscoInterfaceDriver
from app.drivers.huawei.interface import HuaweiInterfaceDriver

# System Drivers
from app.drivers.openconfig.system import OpenConfigSystemDriver
from app.drivers.cisco.system import CiscoSystemDriver
from app.drivers.huawei.system import HuaweiSystemDriver

# Routing Drivers
from app.drivers.openconfig.routing import OpenConfigRoutingDriver
from app.drivers.cisco.routing import CiscoRoutingDriver
from app.drivers.huawei.routing import HuaweiRoutingDriver

# VLAN Drivers
from app.drivers.openconfig.vlan import OpenConfigVlanDriver
from app.drivers.cisco.vlan import CiscoVlanDriver
from app.drivers.huawei.vlan import HuaweiVlanDriver

# DHCP Drivers
from app.drivers.huawei.dhcp import HuaweiDhcpDriver

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
        self.vlan_normalizer = VlanNormalizer()
        self.dhcp_normalizer = DhcpNormalizer()

        # Register drivers by vendor and category
        self.interface_drivers = {
            "openconfig": OpenConfigInterfaceDriver(),
            "cisco": CiscoInterfaceDriver(),
            "huawei": HuaweiInterfaceDriver(),
        }
        
        self.system_drivers = {
            "openconfig": OpenConfigSystemDriver(),
            "cisco": CiscoSystemDriver(),
            "huawei": HuaweiSystemDriver(),
        }
        
        self.routing_drivers = {
            "openconfig": OpenConfigRoutingDriver(),
            "cisco": CiscoRoutingDriver(),
            "huawei": HuaweiRoutingDriver(),
        }
        
        # VLAN drivers
        self.vlan_drivers = {
            "openconfig": OpenConfigVlanDriver(),
            "cisco": CiscoVlanDriver(),
            "huawei": HuaweiVlanDriver(),
        }
        
        # DHCP drivers
        self.dhcp_drivers = {
            "huawei": HuaweiDhcpDriver(),
        }
        
        # Device driver (mount/unmount)
        self.device_driver = DeviceDriver()
    
    def _get_driver(self, intent: str, driver_name: str):
        """Get appropriate driver based on intent category"""
        intent_def = IntentRegistry.get(intent)
        if not intent_def:
            raise UnsupportedIntent(intent)
        
        # เลือก driver ตาม category
        if intent_def.category == IntentCategory.INTERFACE:
            return self.interface_drivers.get(driver_name)
        
        elif intent_def.category == IntentCategory.ROUTING:
            return self.routing_drivers.get(driver_name)
        
        elif intent_def.category == IntentCategory.SYSTEM:
            return self.system_drivers.get(driver_name)
        
        elif intent_def.category == IntentCategory.VLAN:
            return self.vlan_drivers.get(driver_name)
        
        elif intent_def.category == IntentCategory.DHCP:
            return self.dhcp_drivers.get(driver_name)
        
        elif intent_def.category == IntentCategory.SHOW:
            # Show intents - route to correct driver based on intent
            if intent in [Intents.SHOW.INTERFACE, Intents.SHOW.INTERFACES]:
                return self.interface_drivers.get(driver_name)
            elif intent in [Intents.SHOW.RUNNING_CONFIG, Intents.SHOW.VERSION]:
                return self.system_drivers.get(driver_name)
            elif intent in [Intents.SHOW.IP_ROUTE, Intents.SHOW.IP_INTERFACE_BRIEF,
                           Intents.SHOW.OSPF_NEIGHBORS, Intents.SHOW.OSPF_DATABASE]:
                return self.routing_drivers.get(driver_name)
            elif intent == Intents.SHOW.VLANS:
                return self.vlan_drivers.get(driver_name)
            elif intent == Intents.SHOW.DHCP_POOLS:
                return self.dhcp_drivers.get(driver_name)
            else:
                return self.interface_drivers.get(driver_name)
        
        # Default to interface drivers
        return self.interface_drivers.get(driver_name)
    
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
        
        # Special handling for DEVICE category (no device profile needed for some operations)
        if intent_def.category == IntentCategory.DEVICE:
            return await self._handle_device_intent(req)
        
        # Step 3: Get device profile และ check mount status
        device = await self.device_profiles.get(req.node_id)
        
        # Step 3.1: Check if device is mounted and connected
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
        
        # Step 4: Get driver directly from factory (deterministic - no fallback)
        intent_def = IntentRegistry.get(req.intent)
        driver_name = device.vendor  # Use vendor directly, no strategy decision
        
        logger.info(f"Intent: {req.intent}, Device: {req.node_id}, "
                   f"Driver: {driver_name} (deterministic, no fallback)")
        
        # Step 5: Execute with native driver (no fallback mechanism)
        return await self._execute(req, device, "deterministic", driver_name)

    async def _handle_device_intent(self, req: IntentRequest) -> IntentResponse:
        """
        Handle device management intents (status/list)
        These don't require device profile lookup
        
        Note: mount/unmount removed - use dedicated REST endpoints:
            POST /api/v1/nbi/devices/{node_id}/mount
            POST /api/v1/nbi/devices/{node_id}/unmount
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
            strategy_used="direct",
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

    async def _execute(self, req: IntentRequest, device, strategy_used: str, driver_name: str) -> IntentResponse:
        """Execute intent with specific driver"""
        driver = self._get_driver(req.intent, driver_name)
        
        if not driver:
            raise UnsupportedIntent(f"No driver found for {req.intent} with {driver_name}")
        
        # Build RESTCONF request spec
        spec = driver.build(device, req.intent, req.params)
        logger.debug(f"RequestSpec: {spec.method} {spec.path}")

        # Send to ODL
        raw = await self.client.send(spec)

        # Normalize response if needed (pass node_id for routing normalizers)
        result = self._normalize_response(req.intent, driver_name, raw, req.node_id)

        return IntentResponse(
            success=True,
            intent=req.intent,
            node_id=req.node_id,
            strategy_used=strategy_used,
            driver_used=driver_name,
            result=result
        )
    
    def _normalize_response(self, intent: str, driver_name: str, raw: Dict[str, Any], device_id: str = "") -> Dict[str, Any]:
        """Normalize response based on intent type"""
        
        # Check if intent needs normalization
        intent_def = IntentRegistry.get(intent)
        if not intent_def or not intent_def.needs_normalization:
            return raw
        
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
        
        # VLAN normalization
        if intent == Intents.SHOW.VLANS:
            return self.vlan_normalizer.normalize_show_vlans(driver_name, raw)
        
        # DHCP normalization
        if intent == Intents.SHOW.DHCP_POOLS:
            return self.dhcp_normalizer.normalize_show_dhcp_pools(driver_name, raw)
        
        return raw
    
    def get_supported_intents(self) -> Dict[str, Any]:
        """Get list of all supported intents (for API discovery)"""
        return IntentRegistry.get_supported_intents()
