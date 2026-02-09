"""
Cisco Interface Driver
รองรับ IETF + Cisco YANG models สำหรับ Interface operations

Refactored to support:
- configure_interface(): Unified InterfaceConfig -> Cisco-IOS-XE-native payload
- get_interface(): Read interface for Normalizer
- PATCH method for safe config merge (RFC-8040)
"""
from typing import Any, Dict
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.schemas.unified import InterfaceConfig
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class CiscoInterfaceDriver(BaseDriver):
    name = "cisco"

    # Intents ที่ driver นี้รองรับ
    SUPPORTED_INTENTS = {
        Intents.INTERFACE.SET_IPV4,
        Intents.INTERFACE.SET_IPV6,
        Intents.INTERFACE.ENABLE,
        Intents.INTERFACE.DISABLE,
        Intents.INTERFACE.SET_DESCRIPTION,
        Intents.INTERFACE.SET_MTU,
        Intents.SHOW.INTERFACE,
        Intents.SHOW.INTERFACES,
    }

    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        mount = odl_mount_base(device.node_id)

        # ===== INTERFACE SET IPv4 =====
        if intent == Intents.INTERFACE.SET_IPV4:
            return self._build_set_ipv4(mount, params)
        
        # ===== INTERFACE SET IPv6 =====
        if intent == Intents.INTERFACE.SET_IPV6:
            return self._build_set_ipv6(mount, params)
        
        # ===== INTERFACE ENABLE =====
        if intent == Intents.INTERFACE.ENABLE:
            return self._build_enable(mount, params, enabled=True)
        
        # ===== INTERFACE DISABLE =====
        if intent == Intents.INTERFACE.DISABLE:
            return self._build_enable(mount, params, enabled=False)
        
        # ===== INTERFACE SET DESCRIPTION =====
        if intent == Intents.INTERFACE.SET_DESCRIPTION:
            return self._build_set_description(mount, params)
        
        # ===== INTERFACE SET MTU =====
        if intent == Intents.INTERFACE.SET_MTU:
            return self._build_set_mtu(mount, params)
        
        # ===== SHOW INTERFACE =====
        if intent == Intents.SHOW.INTERFACE:
            return self._build_show_interface(mount, params)
        
        # ===== SHOW INTERFACES (all) =====
        if intent == Intents.SHOW.INTERFACES:
            return self._build_show_interfaces(mount)

        raise UnsupportedIntent(intent)

    # ===== Builder Methods =====
    
    def _build_set_ipv4(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        ifname = params.get("interface")
        ip = params.get("ip")
        prefix = params.get("prefix")
        if not ifname or not ip or prefix is None:
            raise DriverBuildError("params require interface, ip, prefix")

        netmask = _prefix_to_netmask(int(prefix))
        path = f"{mount}/ietf-interfaces:interfaces/interface={ifname}"

        payload = {
            "ietf-interfaces:interface": {
                "name": ifname,
                "enabled": True,
                "ietf-ip:ipv4": {
                    "address": [{"ip": ip, "netmask": netmask}]
                }
            }
        }

        return RequestSpec(
            method="PATCH",  # Use PATCH for safe merge
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.INTERFACE.SET_IPV4,
            driver=self.name
        )
    
    def _build_set_ipv6(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        ifname = params.get("interface")
        ip = params.get("ip")
        prefix = params.get("prefix")
        if not ifname or not ip or prefix is None:
            raise DriverBuildError("params require interface, ip, prefix")

        path = f"{mount}/ietf-interfaces:interfaces/interface={ifname}"

        payload = {
            "ietf-interfaces:interface": {
                "name": ifname,
                "enabled": True,
                "ietf-ip:ipv6": {
                    "address": [{"ip": ip, "prefix-length": int(prefix)}]
                }
            }
        }

        return RequestSpec(
            method="PATCH",  # Use PATCH for safe merge
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.INTERFACE.SET_IPV6,
            driver=self.name
        )
    
    def _build_enable(self, mount: str, params: Dict[str, Any], enabled: bool) -> RequestSpec:
        ifname = params.get("interface")
        if not ifname:
            raise DriverBuildError("params require interface")

        path = f"{mount}/ietf-interfaces:interfaces/interface={ifname}"
        payload = {
            "ietf-interfaces:interface": {
                "name": ifname,
                "enabled": enabled
            }
        }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.INTERFACE.ENABLE if enabled else Intents.INTERFACE.DISABLE,
            driver=self.name
        )
    
    def _build_set_description(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        ifname = params.get("interface")
        description = params.get("description", "")
        if not ifname:
            raise DriverBuildError("params require interface")

        path = f"{mount}/ietf-interfaces:interfaces/interface={ifname}"
        payload = {
            "ietf-interfaces:interface": {
                "name": ifname,
                "description": description
            }
        }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.INTERFACE.SET_DESCRIPTION,
            driver=self.name
        )
    
    def _build_set_mtu(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        ifname = params.get("interface")
        mtu = params.get("mtu")
        if not ifname or mtu is None:
            raise DriverBuildError("params require interface, mtu")

        path = f"{mount}/ietf-interfaces:interfaces/interface={ifname}"
        payload = {
            "ietf-interfaces:interface": {
                "name": ifname,
                "mtu": int(mtu)
            }
        }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.INTERFACE.SET_MTU,
            driver=self.name
        )
    
    def _build_show_interface(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        ifname = params.get("interface")
        if not ifname:
            raise DriverBuildError("params require interface")

        path = f"{mount}/ietf-interfaces:interfaces/interface={ifname}"
        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.INTERFACE,
            driver=self.name
        )
    
    def _build_show_interfaces(self, mount: str) -> RequestSpec:
        path = f"{mount}/ietf-interfaces:interfaces"
        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.INTERFACES,
            driver=self.name
        )


    # ===== New Unified Methods (Driver Factory Pattern) =====
    
    def configure_interface(self, device: DeviceProfile, config: InterfaceConfig) -> RequestSpec:
        """
        Configure interface from Unified InterfaceConfig -> Cisco-IOS-XE-native payload
        Uses PATCH method for safe config merge (RFC-8040 compliant)
        
        Args:
            device: Device profile
            config: Unified interface configuration
            
        Returns:
            RequestSpec with Cisco-native payload
        """
        mount = odl_mount_base(device.node_id)
        path = f"{mount}/ietf-interfaces:interfaces/interface={config.name}"
        
        # Build base payload
        interface_payload = {
            "name": config.name,
            "enabled": config.enabled,
        }
        
        # Add IPv4 if specified
        if config.ip and config.mask:
            # แปลง mask: ถ้าเป็นตัวเลข (CIDR) ให้แปลงเป็น dotted decimal
            if config.mask.isdigit():
                netmask = _prefix_to_netmask(int(config.mask))
            else:
                netmask = config.mask
            
            interface_payload["ietf-ip:ipv4"] = {
                "address": [{"ip": config.ip, "netmask": netmask}]
            }
        
        # Add description if specified
        if config.description:
            interface_payload["description"] = config.description
        
        # Add MTU if specified
        if config.mtu:
            interface_payload["mtu"] = config.mtu
        
        payload = {"ietf-interfaces:interface": interface_payload}
        
        return RequestSpec(
            method="PATCH",  # Use PATCH for safe merge
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent="interface.configure",
            driver=self.name
        )
    
    def get_interface(self, device: DeviceProfile, name: str) -> RequestSpec:
        """
        Get interface configuration for Normalizer to process
        
        Args:
            device: Device profile
            name: Interface name
            
        Returns:
            RequestSpec for GET operation
        """
        mount = odl_mount_base(device.node_id)
        path = f"{mount}/ietf-interfaces:interfaces/interface={name}"
        
        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent="show.interface",
            driver=self.name
        )


# ===== Utility Functions =====
def _prefix_to_netmask(prefix: int) -> str:
    """Convert CIDR prefix to dotted decimal netmask"""
    if prefix < 0 or prefix > 32:
        return "0.0.0.0"
    mask = (0xffffffff << (32 - prefix)) & 0xffffffff
    return ".".join(str((mask >> (8*i)) & 0xff) for i in [3, 2, 1, 0])
