from dataclasses import dataclass
from typing import Literal
from app.schemas.device_profile import DeviceProfile

Strategy = Literal["oc-first", "vendor-first"]

@dataclass
class StrategyDecision:
    strategy_used: Strategy
    primary_driver: str
    fallback_driver: str

class StrategyResolver:
    def decide(self, device: DeviceProfile, intent: str) -> StrategyDecision:
        if device.default_strategy == "vendor-first":
            return StrategyDecision(
                strategy_used="vendor-first",
                primary_driver=device.vendor,
                fallback_driver="openconfig"
            )

        # default oc-first
        oc_ok = device.oc_supported_intents.get(intent, False)
        if oc_ok:
            return StrategyDecision("oc-first", "openconfig", device.vendor)
        return StrategyDecision("oc-first", device.vendor, "openconfig")

    def should_fallback(self, status: int, body_text: str) -> bool:
        if status == 404:
            return True
        if status == 400:
            b = (body_text or "").lower()
            keywords = ["unknown", "schema", "namespace", "not found", "invalid"]
            return any(k in b for k in keywords)
        return False
