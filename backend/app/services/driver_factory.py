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
    _vlan_drivers: Dict[str, Type[BaseDriver]] = {}
    _dhcp_drivers: Dict[str, Type[BaseDriver]] = {}
    
    @classmethod
    def _load_drivers(cls):
        """Load all driver classes (lazy loading to avoid circular imports)"""
        if cls._drivers_loaded:
            return
        
        # Interface Drivers
        from app.drivers.cisco.interface import CiscoInterfaceDriver
        from app.drivers.huawei.interface import HuaweiInterfaceDriver
        from app.drivers.openconfig.interface import OpenConfigInterfaceDriver
        
        cls._interface_drivers = {
            "cisco": CiscoInterfaceDriver,
            "huawei": HuaweiInterfaceDriver,
            "openconfig": OpenConfigInterfaceDriver,
        }
        
        # Routing Drivers
        from app.drivers.cisco.routing import CiscoRoutingDriver
        from app.drivers.huawei.routing import HuaweiRoutingDriver
        from app.drivers.openconfig.routing import OpenConfigRoutingDriver
        
        cls._routing_drivers = {
            "cisco": CiscoRoutingDriver,
            "huawei": HuaweiRoutingDriver,
            "openconfig": OpenConfigRoutingDriver,
        }
        
        # System Drivers
        from app.drivers.cisco.system import CiscoSystemDriver
        from app.drivers.huawei.system import HuaweiSystemDriver
        from app.drivers.openconfig.system import OpenConfigSystemDriver
        
        cls._system_drivers = {
            "cisco": CiscoSystemDriver,
            "huawei": HuaweiSystemDriver,
            "openconfig": OpenConfigSystemDriver,
        }
        
        # VLAN Drivers
        from app.drivers.cisco.vlan import CiscoVlanDriver
        from app.drivers.huawei.vlan import HuaweiVlanDriver
        from app.drivers.openconfig.vlan import OpenConfigVlanDriver
        
        cls._vlan_drivers = {
            "cisco": CiscoVlanDriver,
            "huawei": HuaweiVlanDriver,
            "openconfig": OpenConfigVlanDriver,
        }
        
        # DHCP Drivers (Huawei only for now)
        from app.drivers.huawei.dhcp import HuaweiDhcpDriver
        
        cls._dhcp_drivers = {
            "huawei": HuaweiDhcpDriver,
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
            IntentCategory.VLAN: cls._vlan_drivers,
            IntentCategory.DHCP: cls._dhcp_drivers,
            IntentCategory.SHOW: cls._interface_drivers,  # Default for show operations
        }
        
        return registries.get(category, cls._interface_drivers)
    
    @classmethod
    def get_driver(
        cls,
        node_id: str,
        vendor: str,
        category: IntentCategory = IntentCategory.INTERFACE
    ) -> BaseDriver:
        """
        Get the appropriate native driver for a vendor (deterministic - no fallback)
        
        Args:
            node_id: Device node identifier (for logging/context)
            vendor: Vendor name ("cisco", "huawei")
            category: Intent category to select driver type
            
        Returns:
            Instantiated native driver
            
        Raises:
            UnsupportedVendor: If vendor is not supported for the given category
        """
        vendor_lower = vendor.lower()
        registry = cls._get_registry(category)
        
        driver_class = registry.get(vendor_lower)
        if not driver_class:
            raise UnsupportedVendor(
                f"Vendor '{vendor}' is not supported for category '{category.value}'. "
                f"Supported vendors: {list(registry.keys())}"
            )
        
        return driver_class()
    
    @classmethod
    def get_supported_vendors(cls, category: IntentCategory = IntentCategory.INTERFACE) -> list:
        """Get list of supported vendors for a category"""
        registry = cls._get_registry(category)
        return list(registry.keys())
    
    @classmethod
    def is_vendor_supported(cls, vendor: str, category: IntentCategory = IntentCategory.INTERFACE) -> bool:
        """Check if a vendor is supported for a category"""
        registry = cls._get_registry(category)
        return vendor.lower() in registry
