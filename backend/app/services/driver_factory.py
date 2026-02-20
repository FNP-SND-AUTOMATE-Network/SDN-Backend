"""
Driver Factory - Deterministic Native Driver Selection

Usage:
    driver = DriverFactory.get_driver(node_id="CSR1", vendor="cisco")
    spec = driver.configure_interface(device, config)
"""
from typing import Dict, Type, Optional
from app.drivers.base import BaseDriver
from app.core.errors import UnsupportedVendor
from app.core.intent_registry import IntentCategory


class DriverFactory:
    """
    Factory for creating Native Driver based on vendor
    
    Architecture:
        - No fallback mechanism
        - Select driver directly from vendor specified in device profile
        - Support multiple categories (interface, routing, system, etc.)
    """
    
    # Lazy loading - import drivers when needed
    _drivers_loaded = False
    _interface_drivers: Dict[str, Type[BaseDriver]] = {}
    _routing_drivers: Dict[str, Type[BaseDriver]] = {}
    _system_drivers: Dict[str, Type[BaseDriver]] = {}
    _dhcp_drivers: Dict[str, Type[BaseDriver]] = {}
    
    @classmethod
    def _load_drivers(cls):
        """Load all driver classes (lazy loading to avoid circular imports)"""
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
        
        # DHCP Drivers (Huawei only for now)
        from app.drivers.huawei.vrp8.dhcp import HuaweiDhcpDriver
        
        cls._dhcp_drivers = {
            "HUAWEI_VRP": HuaweiDhcpDriver,
        }
        
        cls._drivers_loaded = True
    
    @classmethod
    def _get_registry(cls, category: IntentCategory) -> Dict[str, Type[BaseDriver]]:
        """Get the appropriate driver registry for a category"""
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
        Get the appropriate native driver based on OS Type (preferred) or Vendor (fallback)
        
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
        """Get list of supported vendors/os_types for a category"""
        registry = cls._get_registry(category)
        return list(registry.keys())
    
    @classmethod
    def is_vendor_supported(cls, vendor: str, category: IntentCategory = IntentCategory.INTERFACE) -> bool:
        """
        Check if a vendor OR os_type is supported
        """
        registry = cls._get_registry(category)
        return vendor in registry or vendor.lower() in registry

    @classmethod
    def get_intents_by_os(cls) -> dict:
        """
        Get all supported intents grouped by OS type.
        
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
