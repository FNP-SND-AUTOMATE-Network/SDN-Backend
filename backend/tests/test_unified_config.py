import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.intent_service import IntentService, IntentRequest, IntentResponse
from app.core.intent_registry import Intents, IntentRegistry
from app.normalizers.config import ConfigNormalizer

class TestUnifiedConfig(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        # Patch dependencies
        self.odl_patcher = patch('app.services.intent_service.OdlRestconfClient')
        self.device_patcher = patch('app.services.intent_service.DeviceProfileService')
        
        self.MockOdlClient = self.odl_patcher.start()
        self.MockDeviceService = self.device_patcher.start()
        
        # Setup mocks
        self.mock_client = self.MockOdlClient.return_value
        self.mock_client.send = AsyncMock(return_value={"status": "ok"})
        
        self.mock_device_service = self.MockDeviceService.return_value
        self.mock_device_service.get = AsyncMock(return_value=MagicMock(vendor="cisco"))
        self.mock_device_service.check_mount_status = AsyncMock(return_value={"ready_for_intent": True})
        
        self.service = IntentService()

    async def asyncTearDown(self):
        self.odl_patcher.stop()
        self.device_patcher.stop()

    async def test_config_normalizer_direct(self):
        """Test ConfigNormalizer logic directly"""
        normalizer = ConfigNormalizer()
        
        # Test Interface Config
        intent = "interface.set_ipv4"
        params = {"interface": "Gi1", "ip": "192.168.1.1", "prefix": 24}
        result = normalizer.normalize(intent, "cisco", {}, params)
        
        self.assertTrue(result["success"])
        self.assertIn("Set IPv4 192.168.1.1 on Gi1", result["changes"][0])
        
        # Test Routing Config
        intent = "routing.static.add"
        params = {"prefix": "10.0.0.0/24", "next_hop": "192.168.1.254"}
        result = normalizer.normalize(intent, "huawei", {}, params)
        
        self.assertTrue(result["success"])
        self.assertIn("Added static route 10.0.0.0/24 via 192.168.1.254", result["changes"][0])

    async def test_intent_service_config_flow(self):
        """Test full flow through IntentService for a config intent"""
        
        # Create a config request
        req = IntentRequest(
            intent="interface.enable",
            node_id="CSR1000v",
            params={"interface": "Gi2"}
        )
        
        # Mock _get_driver to avoid actual driver instantiation if needed, 
        # but factory usage is fine if drivers don't have side effects on init.
        # Drivers are lightweight, so we can let them execute or mock them.
        # Let's mock _execute to focus on IntentService logic or just _get_driver.
        
        # Mocking _get_driver to return a mock driver that returns a specific spec
        with patch.object(self.service, '_get_driver') as mock_get_driver:
            mock_driver = MagicMock()
            mock_driver.build.return_value = MagicMock(method="POST", path="/test")
            mock_get_driver.return_value = mock_driver
            
            resp = await self.service.handle(req)
            
            self.assertTrue(resp.success)
            self.assertEqual(resp.intent, "interface.enable")
            # Check normalized result
            self.assertTrue(resp.result["success"])
            self.assertIn("Enabled interface Gi2", resp.result["changes"][0])

    async def test_show_intent_normalization_enabled(self):
        """Verify SHOW intents also go through normalization check"""
        req = IntentRequest(
            intent="show.version",
            node_id="CSR1000v",
            params={}
        )
        
        with patch.object(self.service, '_get_driver') as mock_get_driver:
            mock_driver = MagicMock()
            mock_driver.build.return_value = MagicMock(method="POST", path="/test")
            mock_get_driver.return_value = mock_driver
            
            # Mock ODL response for show version
            self.service.client.send.return_value = {
                "native": {
                    "version": "16.09.04"
                }
            }
            
            # Mock SystemNormalizer
            with patch('app.services.intent_service.SystemNormalizer') as MockSysNorm:
                sys_norm_instance = MockSysNorm.return_value
                sys_norm_instance.normalize_show_version.return_value = {"version": "unified-1.0"}
                
                # Replace the normalizer instance on our service
                self.service.system_normalizer = sys_norm_instance
                
                resp = await self.service.handle(req)
                
                self.assertEqual(resp.result, {"version": "unified-1.0"})

if __name__ == '__main__':
    unittest.main()
