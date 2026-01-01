"""
Intent Service - Core service สำหรับ handle Intent requests
รองรับ multi-vendor, strategy pattern และ fallback mechanism
"""
from typing import Dict, Any
from app.schemas.intent import IntentRequest, IntentResponse
from app.services.device_profile_service import DeviceProfileService
from app.services.strategy_resolver import StrategyResolver
from app.clients.odl_restconf_client import OdlRestconfClient
from app.normalizers.interface import InterfaceNormalizer
from app.normalizers.system import SystemNormalizer
from app.normalizers.routing import RoutingNormalizer, InterfaceBriefNormalizer, OspfNormalizer
from app.core.errors import OdlRequestError, UnsupportedIntent
from app.core.intent_registry import IntentRegistry, Intents, IntentCategory
from app.core.logging import logger

# Interface Drivers
from app.drivers.openconfig.interface import OpenConfigInterfaceDriver
from app.drivers.cisco.interface import CiscoInterfaceDriver
from app.drivers.huawei.interface import HuaweiInterfaceDriver

# System Drivers
from app.drivers.openconfig.system import OpenConfigSystemDriver
from app.drivers.cisco.system import CiscoSystemDriver

# Routing Drivers
from app.drivers.openconfig.routing import OpenConfigRoutingDriver
from app.drivers.cisco.routing import CiscoRoutingDriver


class IntentService:
    """
    Main service for handling Intent-based requests
    
    Flow:
    1. Validate intent exists in registry
    2. Get device profile
    3. Strategy resolver decides which driver to use
    4. Driver builds RESTCONF request
    5. Send to ODL via client
    6. Normalize response if needed
    7. Return unified response
    """
    
    def __init__(self):
        self.device_profiles = DeviceProfileService()
        self.strategy = StrategyResolver()
        self.client = OdlRestconfClient()
        
        # Normalizers
        self.interface_normalizer = InterfaceNormalizer()
        self.system_normalizer = SystemNormalizer()

        # Register drivers by vendor and category
        self.interface_drivers = {
            "openconfig": OpenConfigInterfaceDriver(),
            "cisco": CiscoInterfaceDriver(),
            "huawei": HuaweiInterfaceDriver(),
        }
        
        self.system_drivers = {
            "openconfig": OpenConfigSystemDriver(),
            "cisco": CiscoSystemDriver(),
            # "huawei": HuaweiSystemDriver(),  # TODO: add later
        }
        
        self.routing_drivers = {
            "openconfig": OpenConfigRoutingDriver(),
            "cisco": CiscoRoutingDriver(),
            # "huawei": HuaweiRoutingDriver(),  # TODO: add later
        }
    
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
        
        elif intent_def.category == IntentCategory.SHOW:
            # Show intents - route to correct driver based on intent
            if intent in [Intents.SHOW.INTERFACE, Intents.SHOW.INTERFACES]:
                return self.interface_drivers.get(driver_name)
            elif intent in [Intents.SHOW.RUNNING_CONFIG, Intents.SHOW.VERSION]:
                return self.system_drivers.get(driver_name)
            elif intent in [Intents.SHOW.IP_ROUTE, Intents.SHOW.IP_INTERFACE_BRIEF,
                           Intents.SHOW.OSPF_NEIGHBORS, Intents.SHOW.OSPF_DATABASE]:
                return self.routing_drivers.get(driver_name)
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
        
        # Step 3: Get device profile
        device = self.device_profiles.get(req.deviceId)
        
        # Step 4: Decide strategy
        decision = self.strategy.decide(device, req.intent)
        
        logger.info(f"Intent: {req.intent}, Device: {req.deviceId}, "
                   f"Strategy: {decision.strategy_used}, Primary: {decision.primary_driver}")

        # Step 5: Try primary driver
        try:
            return await self._execute(req, device, decision.strategy_used, decision.primary_driver)

        except OdlRequestError as e:
            # Step 6: Check fallback condition
            details = e.detail if isinstance(e.detail, dict) else {"details": str(e.detail)}
            status = details.get("details", {}).get("status", e.status_code)
            body = details.get("details", {}).get("body", "")

            fallback_driver = self._get_driver(req.intent, decision.fallback_driver)
            if (fallback_driver and 
                self.strategy.should_fallback(int(status), str(body))):
                logger.info(f"Fallback to {decision.fallback_driver}")
                return await self._execute(req, device, decision.strategy_used, decision.fallback_driver)

            raise

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

        # Normalize response if needed (pass device_id for routing normalizers)
        result = self._normalize_response(req.intent, driver_name, raw, req.deviceId)

        return IntentResponse(
            success=True,
            intent=req.intent,
            deviceId=req.deviceId,
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
        
        return raw
    
    def get_supported_intents(self) -> Dict[str, Any]:
        """Get list of all supported intents (for API discovery)"""
        return IntentRegistry.get_supported_intents()
