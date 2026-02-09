"""
Base Driver - Abstract base class for all vendor drivers

Support both legacy build() method and new configure_interface()/get_interface() methods
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.schemas.unified import InterfaceConfig


class BaseDriver(ABC):
    """
    Abstract Base Driver class
    
    All vendor-specific drivers must inherit from this class
    and implement the required abstract methods.
    """
    name: str

    @abstractmethod
    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Build RESTCONF request spec from intent and params (legacy method)
        
        Args:
            device: Device profile with vendor info
            intent: Intent name (e.g., "interface.set_ipv4")
            params: Intent parameters
            
        Returns:
            RequestSpec for ODL RESTCONF client
        """
        ...
    
    def configure_interface(self, device: DeviceProfile, config: InterfaceConfig) -> RequestSpec:
        """
        Configure interface using Unified Intent JSON
        
        Translates InterfaceConfig to vendor-native payload using PATCH method.
        Subclasses should override this method.
        
        Args:
            device: Device profile
            config: Unified interface configuration
            
        Returns:
            RequestSpec with vendor-native payload
        """
        # Default implementation: convert InterfaceConfig to params and use build()
        params = {
            "interface": config.name,
            "ip": config.ip,
            "prefix": config.mask,
            "description": config.description,
            "mtu": config.mtu,
        }
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}
        
        # Determine intent based on what's being configured
        if config.ip:
            intent = "interface.set_ipv4"
        elif config.description:
            intent = "interface.set_description"
        elif config.mtu:
            intent = "interface.set_mtu"
        elif config.enabled is False:
            intent = "interface.disable"
        else:
            intent = "interface.enable"
        
        return self.build(device, intent, params)
    
    def get_interface(self, device: DeviceProfile, name: str) -> RequestSpec:
        """
        Get interface configuration from device
        
        Returns raw response for Normalizer to process.
        Subclasses should override this method.
        
        Args:
            device: Device profile
            name: Interface name
            
        Returns:
            RequestSpec for GET operation
        """
        # Default implementation: use build() with show.interface intent
        return self.build(device, "show.interface", {"interface": name})
