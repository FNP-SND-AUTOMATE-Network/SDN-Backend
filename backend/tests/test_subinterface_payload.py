import unittest
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.drivers.cisco.interface import CiscoInterfaceDriver
from app.schemas.device_profile import DeviceProfile
from app.core.intent_registry import Intents

class TestCiscoSubinterface(unittest.TestCase):
    
    def test_build_create_subinterface_payload(self):
        """
        Verify that _build_create_subinterface constructs the correct YANG payload
        matching the user's provided example.
        """
        driver = CiscoInterfaceDriver()
        
        # Mock device
        device = DeviceProfile(
            node_id="CSR1000vT",
            vendor="cisco",
            profile_name="test-profile"
        )
        
        # User params matches the user request:
        # interface="GigabitEthernet2.100" (derived from name="2.100" and parent "GigabitEthernet")
        # vlan_id=100
        # ip="192.168.100.1", prefix=24 (mask 255.255.255.0)
        
        params = {
            "interface": "GigabitEthernet2.100",
            "vlan_id": 100,
            "ip": "192.168.100.1",
            "prefix": 24
        }
        
        spec = driver.build(device, Intents.INTERFACE.CREATE_SUBINTERFACE, params)
        
        # Verify Path
        # Expected: .../interface/GigabitEthernet=2.100
        expected_path = "network-topology:network-topology/topology=topology-netconf/node=CSR1000vT/yang-ext:mount/Cisco-IOS-XE-native:native/interface/GigabitEthernet=2.100"
        self.assertEqual(spec.path, expected_path)
        
        # Verify Payload Structure
        payload = spec.payload
        self.assertIn("Cisco-IOS-XE-native:GigabitEthernet", payload)
        
        interface_list = payload["Cisco-IOS-XE-native:GigabitEthernet"]
        self.assertEqual(len(interface_list), 1)
        
        iface = interface_list[0]
        
        # Check Name
        self.assertEqual(iface["name"], "2.100")
        
        # Check Encapsulation
        self.assertIn("encapsulation", iface)
        self.assertIn("dot1Q", iface["encapsulation"])
        self.assertEqual(iface["encapsulation"]["dot1Q"]["vlan-id"], 100)
        
        # Check IP
        self.assertIn("ip", iface)
        self.assertEqual(iface["ip"]["address"]["primary"]["address"], "192.168.100.1")
        self.assertEqual(iface["ip"]["address"]["primary"]["mask"], "255.255.255.0")
        
        print("Payload verified successfully!")
        
if __name__ == '__main__':
    unittest.main()
