"""
Device Profile Service (Database Version)
ดึงข้อมูล Device Profile จาก Database แทนการ hardcode

สำหรับใช้กับ NBI (Intent-Based API)
"""
from typing import Dict, List, Optional
from app.schemas.device_profile import DeviceProfile
from app.core.errors import DeviceNotFound
from app.core.intent_registry import Intents
from app.database import get_prisma_client
from app.core.logging import logger


class DeviceProfileService:
    """
    Service สำหรับจัดการ Device Profiles
    
    ดึงข้อมูลจาก Database (DeviceNetwork table) และแปลงเป็น DeviceProfile
    สำหรับใช้กับ Intent processing
    """
    
    # Default OpenConfig support by vendor
    DEFAULT_OC_SUPPORT = {
        "CISCO": {
            # Cisco รองรับ OpenConfig ค่อนข้างดี
            Intents.INTERFACE.SET_IPV4: True,
            Intents.INTERFACE.SET_IPV6: True,
            Intents.INTERFACE.ENABLE: True,
            Intents.INTERFACE.DISABLE: True,
            Intents.INTERFACE.SET_DESCRIPTION: True,
            Intents.INTERFACE.SET_MTU: True,
            Intents.SHOW.INTERFACE: True,
            Intents.SHOW.INTERFACES: True,
            Intents.SHOW.VERSION: False,
            Intents.SHOW.IP_ROUTE: False,
            Intents.ROUTING.STATIC_ADD: False,
            Intents.ROUTING.STATIC_DELETE: False,
            Intents.SYSTEM.SET_HOSTNAME: False,
            Intents.SYSTEM.SET_NTP: False,
        },
        "HUAWEI": {
            # Huawei มักไม่รองรับ OpenConfig เต็มที่
            Intents.INTERFACE.SET_IPV4: False,
            Intents.INTERFACE.SET_IPV6: False,
            Intents.INTERFACE.ENABLE: False,
            Intents.INTERFACE.DISABLE: False,
            Intents.SHOW.INTERFACE: False,
            Intents.SHOW.INTERFACES: False,
        },
        "JUNIPER": {
            # Juniper รองรับ OpenConfig ดี
            Intents.INTERFACE.SET_IPV4: True,
            Intents.INTERFACE.ENABLE: True,
            Intents.INTERFACE.DISABLE: True,
            Intents.SHOW.INTERFACE: True,
            Intents.SHOW.INTERFACES: True,
        },
        "ARISTA": {
            # Arista รองรับ OpenConfig ดีมาก
            Intents.INTERFACE.SET_IPV4: True,
            Intents.INTERFACE.SET_IPV6: True,
            Intents.INTERFACE.ENABLE: True,
            Intents.INTERFACE.DISABLE: True,
            Intents.SHOW.INTERFACE: True,
            Intents.SHOW.INTERFACES: True,
        },
        "OTHER": {
            # Default: ไม่รองรับ OC
        }
    }
    
    # Strategy mapping
    STRATEGY_MAP = {
        "OC_FIRST": "oc-first",
        "VENDOR_FIRST": "vendor-first",
        "OC_ONLY": "oc-only",
        "VENDOR_ONLY": "vendor-only"
    }
    
    def __init__(self):
        self._cache: Dict[str, DeviceProfile] = {}  # Optional caching
    
    def _db_to_profile(self, db_device) -> DeviceProfile:
        """
        แปลง DeviceNetwork (DB model) เป็น DeviceProfile
        """
        # Get OC support from DB or use default based on vendor
        oc_support = {}
        if db_device.oc_supported_intents:
            # ใช้ค่าจาก DB ถ้ามี
            oc_support = db_device.oc_supported_intents
        else:
            # ใช้ default ตาม vendor
            vendor = db_device.vendor if db_device.vendor else "OTHER"
            oc_support = self.DEFAULT_OC_SUPPORT.get(vendor, {})
        
        # Map strategy
        strategy = self.STRATEGY_MAP.get(
            db_device.default_strategy if db_device.default_strategy else "OC_FIRST",
            "oc-first"
        )
        
        # Map type to role
        role = "router" if db_device.type == "ROUTER" else "switch"
        
        return DeviceProfile(
            device_id=db_device.id,
            node_id=db_device.node_id or db_device.device_name,  # fallback to device_name
            vendor=(db_device.vendor or "OTHER").lower(),
            model=db_device.device_model,
            role=role,
            default_strategy=strategy,
            oc_supported_intents=oc_support
        )
    
    async def get(self, device_id: str) -> DeviceProfile:
        """
        Get device profile by ID (database ID หรือ node_id)
        
        Args:
            device_id: Can be either database UUID or node_id
        """
        prisma = get_prisma_client()
        
        # Try to find by node_id first (for NBI compatibility)
        device = await prisma.devicenetwork.find_first(
            where={"node_id": device_id}
        )
        
        # If not found, try by database ID
        if not device:
            try:
                device = await prisma.devicenetwork.find_unique(
                    where={"id": device_id}
                )
            except Exception:
                pass
        
        # If still not found, try by device_name
        if not device:
            device = await prisma.devicenetwork.find_first(
                where={"device_name": device_id}
            )
        
        if not device:
            raise DeviceNotFound(device_id)
        
        return self._db_to_profile(device)
    
    async def get_by_node_id(self, node_id: str) -> DeviceProfile:
        """Get device profile by ODL node_id"""
        prisma = get_prisma_client()
        
        device = await prisma.devicenetwork.find_first(
            where={"node_id": node_id}
        )
        
        if not device:
            raise DeviceNotFound(f"node_id: {node_id}")
        
        return self._db_to_profile(device)
    
    async def list_all(self) -> List[DeviceProfile]:
        """Get all device profiles"""
        prisma = get_prisma_client()
        
        devices = await prisma.devicenetwork.find_many(
            order={"device_name": "asc"}
        )
        
        return [self._db_to_profile(d) for d in devices]
    
    async def list_mounted(self) -> List[DeviceProfile]:
        """Get only devices that are mounted in ODL"""
        prisma = get_prisma_client()
        
        devices = await prisma.devicenetwork.find_many(
            where={
                "odl_mounted": True,
                "node_id": {"not": None}
            },
            order={"device_name": "asc"}
        )
        
        return [self._db_to_profile(d) for d in devices]
    
    async def list_by_vendor(self, vendor: str) -> List[DeviceProfile]:
        """Get devices filtered by vendor"""
        prisma = get_prisma_client()
        
        # Map string to enum
        vendor_enum = vendor.upper()
        
        devices = await prisma.devicenetwork.find_many(
            where={"vendor": vendor_enum},
            order={"device_name": "asc"}
        )
        
        return [self._db_to_profile(d) for d in devices]
    
    async def list_by_role(self, role: str) -> List[DeviceProfile]:
        """Get devices filtered by role (router/switch)"""
        prisma = get_prisma_client()
        
        # Map role to type
        type_enum = "ROUTER" if role.lower() == "router" else "SWITCH"
        
        devices = await prisma.devicenetwork.find_many(
            where={"type": type_enum},
            order={"device_name": "asc"}
        )
        
        return [self._db_to_profile(d) for d in devices]
    
    async def update_oc_support(self, device_id: str, oc_support: Dict[str, bool]) -> DeviceProfile:
        """
        Update OpenConfig support mapping for a device
        
        Args:
            device_id: Device ID (node_id or database ID)
            oc_support: Dict mapping intent name -> bool (supports OC or not)
        """
        prisma = get_prisma_client()
        
        # Find device
        device = await prisma.devicenetwork.find_first(
            where={"node_id": device_id}
        )
        if not device:
            device = await prisma.devicenetwork.find_unique(
                where={"id": device_id}
            )
        
        if not device:
            raise DeviceNotFound(device_id)
        
        # Update OC support
        updated = await prisma.devicenetwork.update(
            where={"id": device.id},
            data={"oc_supported_intents": oc_support}
        )
        
        return self._db_to_profile(updated)
    
    async def check_intent_support(self, device_id: str, intent: str) -> bool:
        """Check if device supports specific intent via OpenConfig"""
        profile = await self.get(device_id)
        return profile.oc_supported_intents.get(intent, False)


# ============================================================
# Synchronous wrapper for backward compatibility
# ============================================================

class DeviceProfileServiceSync:
    """
    Sync wrapper สำหรับ backward compatibility
    ใช้ในกรณีที่ต้องการ sync methods (non-async)
    
    Note: ใช้ in-memory cache แทนการ query DB
    """
    
    def __init__(self):
        self._devices: Dict[str, DeviceProfile] = {}
        self._loaded = False
    
    def _ensure_loaded(self):
        """Load data from cache if not loaded"""
        if not self._loaded:
            logger.warning("DeviceProfileServiceSync: Using empty cache. Call load_from_db() first.")
    
    def get(self, device_id: str) -> DeviceProfile:
        """Get device profile by ID (sync version)"""
        self._ensure_loaded()
        
        # Try node_id first
        for profile in self._devices.values():
            if profile.node_id == device_id:
                return profile
        
        # Try device_id
        if device_id in self._devices:
            return self._devices[device_id]
        
        raise DeviceNotFound(device_id)
    
    def list_all(self) -> List[DeviceProfile]:
        """Get all device profiles (sync version)"""
        self._ensure_loaded()
        return list(self._devices.values())
    
    def add_to_cache(self, profile: DeviceProfile):
        """Add profile to cache"""
        self._devices[profile.device_id] = profile
        self._loaded = True
    
    def clear_cache(self):
        """Clear the cache"""
        self._devices.clear()
        self._loaded = False
