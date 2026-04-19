"""
Driver Factory — Deterministic Native Driver Selection
ระบบเลือก Driver อัตโนมัติตาม Vendor/OS ของอุปกรณ์

หน้าที่หลัก:
- เลือก Driver ที่เหมาะสมจาก vendor/os_type ของอุปกรณ์ (ไม่มี Fallback)
- รองรับหลาย Category: Interface, Routing, System, DHCP
- ใช้ Lazy Loading เพื่อป้องกัน Circular Import
- คืน Driver Instance ที่พร้อมใช้งานสำหรับสร้าง RESTCONF Request

Flow:
    os_type → _get_registry(category) → registry[os_type] → Driver Class → Instance

ตัวอย่าง:
    driver = DriverFactory.get_driver(node_id="CSR1", vendor="cisco", os_type="CISCO_IOS_XE")
    spec = driver.configure_interface(device, config)
"""
from typing import Dict, Type, Optional
from app.drivers.base import BaseDriver
from app.core.errors import UnsupportedVendor
from app.core.intent_registry import IntentCategory


class DriverFactory:
    """
    Factory สำหรับสร้าง Native Driver ตาม Vendor/OS
    
    สถาปัตยกรรม:
    - ไม่มี Fallback → ถ้าไม่รองรับจะ raise UnsupportedVendor ทันที
    - เลือก Driver ตรงจาก os_type ที่ระบุใน Device Profile
    - รองรับหลาย Category (Interface, Routing, System, DHCP)
    """
    
    # Lazy loading - import drivers when needed
    _drivers_loaded = False
    _interface_drivers: Dict[str, Type[BaseDriver]] = {}
    _routing_drivers: Dict[str, Type[BaseDriver]] = {}
    _system_drivers: Dict[str, Type[BaseDriver]] = {}
    _dhcp_drivers: Dict[str, Type[BaseDriver]] = {}
    
    @classmethod
    def _load_drivers(cls):
        """
        โหลด Driver Classes ทั้งหมด (Lazy Loading)
        - เรียกครั้งเดียวตอนใช้งานครั้งแรก
        - ใช้ Lazy Import เพื่อป้องกัน Circular Import
        - ลงทะเบียน Driver ตาม OS Type สำหรับแต่ละ Category
        """
        if cls._drivers_loaded:
            return
        
        # Interface Drivers
        from app.drivers.cisco.ios_xe.interface import CiscoInterfaceDriver
        from app.drivers.huawei.vrp8.interface import HuaweiInterfaceDriver
        cls._interface_drivers = {
            "CISCO_IOS_XE": CiscoInterfaceDriver,
            "HUAWEI_VRP": HuaweiInterfaceDriver,
        }
        
        # Routing Drivers
        from app.drivers.cisco.ios_xe.routing import CiscoRoutingDriver
        from app.drivers.huawei.vrp8.routing import HuaweiRoutingDriver
        cls._routing_drivers = {
            "CISCO_IOS_XE": CiscoRoutingDriver,
            "HUAWEI_VRP": HuaweiRoutingDriver,
        }
        
        # System Drivers
        from app.drivers.cisco.ios_xe.system import CiscoSystemDriver
        from app.drivers.huawei.vrp8.system import HuaweiSystemDriver
        cls._system_drivers = {
            "CISCO_IOS_XE": CiscoSystemDriver,
            "HUAWEI_VRP": HuaweiSystemDriver,
        }
        
        # DHCP Drivers
        from app.drivers.huawei.vrp8.dhcp import HuaweiDhcpDriver
        from app.drivers.cisco.ios_xe.dhcp import CiscoDhcpDriver
        
        cls._dhcp_drivers = {
            "HUAWEI_VRP": HuaweiDhcpDriver,
            "CISCO_IOS_XE": CiscoDhcpDriver,
        }
        
        cls._drivers_loaded = True
    
    @classmethod
    def _get_registry(cls, category: IntentCategory) -> Dict[str, Type[BaseDriver]]:
        """
        ดึง Driver Registry ตาม Category ที่ร้องขอ
        - Interface → _interface_drivers
        - Routing → _routing_drivers
        - System → _system_drivers
        - DHCP → _dhcp_drivers
        """
        cls._load_drivers()
        
        registries = {
            IntentCategory.INTERFACE: cls._interface_drivers,
            IntentCategory.ROUTING: cls._routing_drivers,
            IntentCategory.SYSTEM: cls._system_drivers,
            IntentCategory.DHCP: cls._dhcp_drivers,
            IntentCategory.SHOW: cls._interface_drivers,  # Default for show operations
        }
        
        return registries.get(category, cls._interface_drivers)
    
    @classmethod
    def get_driver(
        cls,
        node_id: str,
        vendor: str,
        os_type: Optional[str] = None,
        category: IntentCategory = IntentCategory.INTERFACE
    ) -> BaseDriver:
        """
        เลือกและสร้าง Driver ที่เหมาะสมตาม OS Type
        - ใช้ os_type เป็นตัวเลือกหลัก (เช่น "CISCO_IOS_XE", "HUAWEI_VRP")
        - ถ้าไม่พบ Driver ที่รองรับจะ raise UnsupportedVendor
        
        Args:
            node_id: Device node identifier (for logging/context)
            vendor: Vendor name ("cisco", "huawei") - Legacy fallback
            os_type: OS Type ("CISCO_IOS_XE", "HUAWEI_VRP") - Preferred
            category: Intent category to select driver type
            
        Returns:
            Instantiated native driver
            
        Raises:
            UnsupportedVendor: If no driver is found
        """
        registry = cls._get_registry(category)
        driver_class = None

        # Try OS Type (only valid selector)
        if os_type:
            driver_class = registry.get(os_type)
            
        if not driver_class:
            msg = f"No driver found for category '{category.value}'."
            if os_type:
                msg += f" os_type='{os_type}' is not supported."
            else:
                msg += f" Device has no os_type set. Please assign an OS type in the database."
            
            raise UnsupportedVendor(msg)
        
        return driver_class()
    
    @classmethod
    def get_supported_vendors(cls, category: IntentCategory = IntentCategory.INTERFACE) -> list:
        """ดึงรายการ Vendor/OS ที่รองรับสำหรับ Category ที่ระบุ"""
        registry = cls._get_registry(category)
        return list(registry.keys())
    
    @classmethod
    def is_vendor_supported(cls, vendor: str, category: IntentCategory = IntentCategory.INTERFACE) -> bool:
        """ตรวจสอบว่า Vendor/OS Type รองรับหรือไม่ใน Category ที่ระบุ"""
        registry = cls._get_registry(category)
        return vendor in registry or vendor.lower() in registry

    @classmethod
    def get_intents_by_os(cls) -> dict:
        """
        ดึงรายการ Intents ทั้งหมดที่รองรับ จัดกลุ่มตาม OS Type
        - สำหรับแสดงใน API ว่า OS ไหนรองรับ Intent อะไรบ้าง
        
        Returns dict like:
        {
            "cisco_ios_xe": {
                "interface": ["interface.set_ipv4", ...],
                "routing": ["routing.static_add", ...],
                ...
            },
            "huawei_vrp8": {
                "interface": ["interface.set_ipv4", ...],
                ...
            }
        }
        """
        cls._load_drivers()
        
        # Map OS label -> list of (category_name, driver_class)
        os_drivers = {
            "cisco_ios_xe": [],
            "huawei_vrp8": [],
        }
        
        # Collect unique driver classes per OS
        category_map = {
            "interface": cls._interface_drivers,
            "routing": cls._routing_drivers,
            "system": cls._system_drivers,
            "dhcp": cls._dhcp_drivers,
        }
        
        for cat_name, registry in category_map.items():
            for key, driver_class in registry.items():
                if key == "CISCO_IOS_XE":
                    os_drivers["cisco_ios_xe"].append((cat_name, driver_class))
                elif key == "HUAWEI_VRP":
                    os_drivers["huawei_vrp8"].append((cat_name, driver_class))
        
        # Build result: deduplicate and collect intents
        result = {}
        for os_label, entries in os_drivers.items():
            seen_classes = set()
            os_intents = {}
            for cat_name, driver_class in entries:
                if driver_class in seen_classes:
                    continue
                seen_classes.add(driver_class)
                intents = sorted(driver_class.SUPPORTED_INTENTS)
                if intents:
                    os_intents[cat_name] = intents
            if os_intents:
                result[os_label] = {
                    "categories": os_intents,
                    "total": sum(len(v) for v in os_intents.values())
                }
        
        return result
