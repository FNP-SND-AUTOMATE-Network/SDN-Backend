"""
Device Profile Service (Database Version)
ดึงข้อมูล Device Profile จาก Database แทนการ hardcode

สำหรับใช้กับ NBI (Intent-Based API)
"""
from typing import Dict, List, Optional, Any
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
    
   
    
    
    # Strategy mapping
    # Strategy mapping
    STRATEGY_MAP = {
        "OPERATION_BASED": "vendor-only",  # Default to vendor-Only
        "OC_FIRST": "vendor-only",
        "VENDOR_FIRST": "vendor-only",
        "OC_ONLY": "vendor-only",
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
        
        # Map strategy - default to vendor-only
        strategy = self.STRATEGY_MAP.get(
            db_device.default_strategy if db_device.default_strategy else "VENDOR_ONLY",
            "vendor-only"
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
    
    async def check_mount_status(self, device_id: str) -> Dict[str, Any]:
        """
        Check if device is mounted and connected in ODL
        
        Args:
            device_id: Can be node_id, database ID, or device_name
            
        Returns:
            {
                "mounted": True/False,
                "connection_status": "CONNECTED/CONNECTING/UNABLE_TO_CONNECT",
                "ready_for_intent": True/False,
                "node_id": "...",
                "message": "..."
            }
        """
        prisma = get_prisma_client()
        
        # Find device by node_id first
        device = await prisma.devicenetwork.find_first(
            where={"node_id": device_id}
        )
        
        # Try by database ID
        if not device:
            try:
                device = await prisma.devicenetwork.find_unique(
                    where={"id": device_id}
                )
            except Exception:
                pass
        
        # Try by device_name
        if not device:
            device = await prisma.devicenetwork.find_first(
                where={"device_name": device_id}
            )
        
        if not device:
            return {
                "mounted": False,
                "connection_status": "UNKNOWN",
                "ready_for_intent": False,
                "node_id": None,
                "message": f"Device '{device_id}' not found in database"
            }
        
        # Check status
        is_mounted = device.odl_mounted or False
        connection_status = device.odl_connection_status or "UNABLE_TO_CONNECT"
        ready_for_intent = is_mounted and connection_status == "CONNECTED"
        
        if not device.node_id:
            return {
                "mounted": False,
                "connection_status": "NOT_CONFIGURED",
                "ready_for_intent": False,
                "node_id": None,
                "device_id": device.id,
                "message": "Device does not have node_id configured"
            }
        
        if not is_mounted:
            message = f"Device '{device.node_id}' is not mounted in ODL"
        elif connection_status == "CONNECTING":
            message = f"Device '{device.node_id}' is still connecting to ODL"
        elif connection_status == "CONNECTED":
            message = f"Device '{device.node_id}' is ready for intent operations"
        else:
            message = f"Device '{device.node_id}' connection failed: {connection_status}"
        
        return {
            "mounted": is_mounted,
            "connection_status": connection_status,
            "ready_for_intent": ready_for_intent,
            "node_id": device.node_id,
            "device_id": device.id,
            "device_name": device.device_name,
            "message": message
        }


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
