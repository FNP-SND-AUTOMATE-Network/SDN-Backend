import sys
import os
import asyncio

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.driver_factory import DriverFactory
from app.services.intent_service import IntentService
from app.services.device_profile_service import DeviceProfileService

def check(condition, message):
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        sys.exit(1)

async def verify():
    print("=== Verifying OpenConfig Removal ===")

    # 1. DriverFactory
    vendors = DriverFactory.get_supported_vendors()
    check("openconfig" not in vendors, "DriverFactory vendors do not include 'openconfig'")
    check("cisco" in vendors, "DriverFactory includes 'cisco'")
    check("huawei" in vendors, "DriverFactory includes 'huawei'")

    # 2. IntentService
    service = IntentService()
    check("openconfig" not in service.interface_drivers, "IntentService.interface_drivers has no 'openconfig'")
    check("openconfig" not in service.routing_drivers, "IntentService.routing_drivers has no 'openconfig'")
    check("openconfig" not in service.system_drivers, "IntentService.system_drivers has no 'openconfig'")
    check("openconfig" not in service.vlan_drivers, "IntentService.vlan_drivers has no 'openconfig'")

    # 3. DeviceProfileService (Mock)
    profile_service = DeviceProfileService()
    profile = profile_service.get("CSR1")
    check(profile.default_strategy == "vendor-only", "CSR1 default_strategy is 'vendor-only'")
    check(profile.oc_supported_intents == {}, "CSR1 oc_supported_intents is empty")

    print("\nALL CHECKS PASSED!")

if __name__ == "__main__":
    asyncio.run(verify())
