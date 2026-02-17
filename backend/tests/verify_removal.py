import unittest
import sys
import os

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.driver_factory import DriverFactory
from app.services.intent_service import IntentService
from app.services.device_profile_service import DeviceProfileService

class TestOpenConfigRemoval(unittest.TestCase):
    def test_driver_factory_vendors(self):
        """Test that DriverFactory does not support 'openconfig' vendor"""
        vendors = DriverFactory.get_supported_vendors()
        self.assertNotIn("openconfig", vendors, "DriverFactory should not support 'openconfig'")
        print("✓ DriverFactory does not support 'openconfig'")

    def test_intent_service_drivers(self):
        """Test that IntentService does not have OpenConfig drivers"""
        service = IntentService()
        self.assertNotIn("openconfig", service.interface_drivers, "IntentService.interface_drivers should not have 'openconfig'")
        self.assertNotIn("openconfig", service.routing_drivers, "IntentService.routing_drivers should not have 'openconfig'")
        self.assertNotIn("openconfig", service.system_drivers, "IntentService.system_drivers should not have 'openconfig'")
        self.assertNotIn("openconfig", service.vlan_drivers, "IntentService.vlan_drivers should not have 'openconfig'")
        print("✓ IntentService drivers match expectation")

    def test_device_profile_defaults(self):
        """Test that DeviceProfileService returns correct defaults (no OC)"""
        service = DeviceProfileService()
        profile = service.get("CSR1")
        self.assertEqual(profile.default_strategy, "vendor-only", "Default strategy should be 'vendor-only'")
        self.assertEqual(profile.oc_supported_intents, {}, "oc_supported_intents should be empty")
        print("✓ DeviceProfileService defaults match expectation")

if __name__ == '__main__':
    unittest.main()
