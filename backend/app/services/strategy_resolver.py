"""
Strategy Resolver - กำหนด Strategy สำหรับเลือก Driver

Strategies:
    - oc-first: ลอง OpenConfig ก่อน แล้ว fallback ไป vendor
    - vendor-first: ลอง vendor ก่อน แล้ว fallback ไป OpenConfig
    - operation-based: GET→OpenConfig, PUT/POST/DELETE→Vendor (RFC-8040 compliant)
"""
from dataclasses import dataclass
from typing import Literal
from app.schemas.device_profile import DeviceProfile
from app.core.intent_registry import IntentRegistry

Strategy = Literal["oc-first", "vendor-first", "operation-based"]

@dataclass
class StrategyDecision:
    strategy_used: Strategy
    primary_driver: str
    fallback_driver: str

class StrategyResolver:
    """
    Resolver สำหรับตัดสินใจว่าจะใช้ driver ไหนเป็น primary และ fallback
    
    Strategy "operation-based" (NEW):
        - Read operations (GET): ใช้ OpenConfig เพื่อ standardized response
        - Config operations (PUT/POST/DELETE/PATCH): ใช้ Vendor YANG + IETF
    """
    
    def decide(self, device: DeviceProfile, intent: str) -> StrategyDecision:
        """
        Decide which driver to use based on device strategy and intent
        
        Args:
            device: Device profile with vendor and strategy info
            intent: Intent name (e.g., "show.interfaces", "interface.set_ipv4")
            
        Returns:
            StrategyDecision with primary and fallback drivers
        """
        # NEW: Operation-based strategy
        if device.default_strategy == "operation-based":
            intent_def = IntentRegistry.get(intent)
            if intent_def and intent_def.is_read_only:
                # GET operations → OpenConfig first (standardized response)
                return StrategyDecision(
                    strategy_used="operation-based",
                    primary_driver="openconfig",
                    fallback_driver=device.vendor
                )
            else:
                # Config operations → Vendor first (full feature support)
                return StrategyDecision(
                    strategy_used="operation-based",
                    primary_driver=device.vendor,
                    fallback_driver="openconfig"
                )
        
        # Existing: vendor-first strategy
        if device.default_strategy == "vendor-first":
            return StrategyDecision(
                strategy_used="vendor-first",
                primary_driver=device.vendor,
                fallback_driver="openconfig"
            )

        # Existing: oc-first strategy (legacy default)
        oc_ok = device.oc_supported_intents.get(intent, False)
        if oc_ok:
            return StrategyDecision("oc-first", "openconfig", device.vendor)
        return StrategyDecision("oc-first", device.vendor, "openconfig")

    def should_fallback(self, status: int, body_text: str) -> bool:
        """
        Determine if we should fallback to secondary driver based on response
        
        Returns True if:
            - 404 Not Found (path/resource doesn't exist)
            - 400 with schema/namespace errors (YANG model not supported)
        """
        if status == 404:
            return True
        if status == 400:
            b = (body_text or "").lower()
            keywords = ["unknown", "schema", "namespace", "not found", "invalid"]
            return any(k in b for k in keywords)
        return False
