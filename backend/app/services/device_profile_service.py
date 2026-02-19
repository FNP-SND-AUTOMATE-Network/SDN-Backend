"""
Device Profile Service
จัดการข้อมูล Device Profile สำหรับใช้ใน Intent processing
"""
from typing import Dict, List, Optional
from app.schemas.device_profile import DeviceProfile
from app.core.errors import DeviceNotFound
from app.core.intent_registry import Intents


class DeviceProfileService:
    """
    Service สำหรับจัดการ Device Profiles
    
    ปัจจุบันใช้ In-Memory storage (สามารถเปลี่ยนเป็น Database ได้ในอนาคต)
    """
    
    def __init__(self):
        self._devices: Dict[str, DeviceProfile] = {
            # ===== Cisco Devices =====
            "CSR1": DeviceProfile(
                device_id="CSR1",
                node_id="CSR1",
                vendor="cisco",
                model="CSR1000v",
                role="router",
            ),
            
            "CSR2": DeviceProfile(
                device_id="CSR2",
                node_id="CSR2",
                vendor="cisco",
                model="CSR1000v",
                role="router",
            ),
            
            # ===== Huawei Devices =====
            "NE40E1": DeviceProfile(
                device_id="NE40E1",
                node_id="NE40E1",
                vendor="huawei",
                model="NE40E",
                role="router",
            ),
            
            "NE40E2": DeviceProfile(
                device_id="NE40E2",
                node_id="NE40E2",
                vendor="huawei",
                model="NE40E-X8",
                role="router",
            ),
            
            # ===== Mixed/Test Devices =====
            "SWITCH1": DeviceProfile(
                device_id="SWITCH1",
                node_id="SWITCH1",
                vendor="cisco",
                model="Nexus9000",
                role="switch",
            ),
        }

    def get(self, device_id: str) -> DeviceProfile:
        """Get device profile by ID"""
        if device_id not in self._devices:
            raise DeviceNotFound(device_id)
        return self._devices[device_id]
    
    def list_all(self) -> List[DeviceProfile]:
        """Get all device profiles"""
        return list(self._devices.values())
    
    def list_by_vendor(self, vendor: str) -> List[DeviceProfile]:
        """Get devices filtered by vendor"""
        return [d for d in self._devices.values() if d.vendor == vendor]
    
    def list_by_role(self, role: str) -> List[DeviceProfile]:
        """Get devices filtered by role (router/switch)"""
        return [d for d in self._devices.values() if d.role == role]
    
    def add(self, profile: DeviceProfile) -> DeviceProfile:
        """Add new device profile"""
        self._devices[profile.device_id] = profile
        return profile
    
    def update(self, device_id: str, updates: Dict) -> DeviceProfile:
        """Update existing device profile"""
        if device_id not in self._devices:
            raise DeviceNotFound(device_id)
        
        device = self._devices[device_id]
        for key, value in updates.items():
            if hasattr(device, key):
                setattr(device, key, value)
        return device
    
    def delete(self, device_id: str) -> bool:
        """Delete device profile"""
        if device_id not in self._devices:
            raise DeviceNotFound(device_id)
        del self._devices[device_id]
        return True
    
    def check_intent_support(self, device_id: str, intent: str) -> bool:
        """Check if device supports specific intent (OpenConfig removed, always returns False)"""
        return False
