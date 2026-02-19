"""
Huawei Interface Driver
Support Huawei YANG models for Interface operations

Refactored to support:
- configure_interface(): Unified InterfaceConfig -> huawei-ifm payload
- get_interface(): Read interface for Normalizer
- PATCH method for safe config merge (RFC-8040)
"""
from typing import Any, Dict
import urllib.parse
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.schemas.unified import InterfaceConfig
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class HuaweiInterfaceDriver(BaseDriver):
    name = "huawei"

    # Intents supported by this driver
    SUPPORTED_INTENTS = {
        Intents.INTERFACE.SET_IPV4,
        Intents.INTERFACE.REMOVE_IPV4,
        Intents.INTERFACE.SET_IPV6,
        Intents.INTERFACE.REMOVE_IPV6,
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
        
        # ===== INTERFACE REMOVE IPv4 =====
        if intent == Intents.INTERFACE.REMOVE_IPV4:
            return self._build_remove_ipv4(mount, params)
        
        # ===== INTERFACE SET IPv6 =====
        if intent == Intents.INTERFACE.SET_IPV6:
            return self._build_set_ipv6(mount, params)
        
        # ===== INTERFACE REMOVE IPv6 =====
        if intent == Intents.INTERFACE.REMOVE_IPV6:
            return self._build_remove_ipv6(mount, params)
        
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

    # ===== Remove IP Methods =====
    
    def _build_remove_ipv4(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Remove IPv4 address from interface (undo ip address)"""
        ifname = params.get("interface")
        if not ifname:
            raise DriverBuildError("params require interface")

        encoded_ifname = urllib.parse.quote(ifname, safe='')
        path = f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}/ipv4Config/am4CfgAddrs"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.INTERFACE.REMOVE_IPV4,
            driver=self.name
        )
    
    def _build_remove_ipv6(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Remove IPv6 address from interface (undo ipv6 address)"""
        ifname = params.get("interface")
        if not ifname:
            raise DriverBuildError("params require interface")

        encoded_ifname = urllib.parse.quote(ifname, safe='')
        path = f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}/ipv6Config"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.INTERFACE.REMOVE_IPV6,
            driver=self.name
        )

    # ===== Builder Methods =====
    
    def _build_set_ipv4(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Configure IPv4 address on interface using VRP8 huawei-ip augmentation.
        
        VRP8 YANG Structure:
        - Base: huawei-ifm:ifm/interfaces/interface={ifName}
        - Augmentation: huawei-ip:ipv4Config
        
        Note: Interface name must be URL-encoded (e.g., Ethernet1%2F0%2F3)
        """
        ifname = params.get("interface")
        ip = params.get("ip")
        prefix = params.get("prefix")
        if not ifname or not ip or prefix is None:
            raise DriverBuildError("params require interface, ip, prefix")

        # URL encode interface name (e.g., Ethernet1/0/3 -> Ethernet1%2F0%2F3)
        encoded_ifname = urllib.parse.quote(ifname, safe='')
        
        # VRP8 path structure
        path = f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}"
        
        # VRP8 ipv4Config structure (no namespace prefix - confirmed working)
        interface_data = {
            "ifName": ifname,
            "ipv4Config": {
                "addrCfgType": "config",
                "am4CfgAddrs": {
                    "am4CfgAddr": [{
                        "ifIpAddr": ip,
                        "subnetMask": _prefix_to_netmask(int(prefix)),
                        "addrType": "main"
                    }]
                }
            }
        }

        # Add description if provided
        description = params.get("description")
        if description:
            interface_data["ifDescr"] = description

        payload = {
            "huawei-ifm:interface": [interface_data]
        }

        return RequestSpec(
            method="PATCH",
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

        encoded_ifname = urllib.parse.quote(ifname, safe='')
        path = f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}"
        payload = {
            "huawei-ifm:interface": [{
                "ifName": ifname,
                "ipv6Config": {
                    "enableFlag": True,
                    "am6CfgAddrs": {
                        "am6CfgAddr": [{
                            "ifIp6Addr": f"{ip}/{prefix}",
                            "addrType6": "global"
                        }]
                    }
                }
            }]
        }

        return RequestSpec(
            method="PATCH",
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

        encoded_ifname = urllib.parse.quote(ifname, safe='')
        path = f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}"
        payload = {
            "huawei-ifm:interface": [{
                "ifName": ifname,
                "ifAdminStatus": "up" if enabled else "down"
            }]
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

        encoded_ifname = urllib.parse.quote(ifname, safe='')
        path = f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}"
        payload = {
            "huawei-ifm:interface": [{
                "ifName": ifname,
                "ifDescr": description
            }]
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

        encoded_ifname = urllib.parse.quote(ifname, safe='')
        path = f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}"
        payload = {
            "huawei-ifm:interface": [{
                "ifName": ifname,
                "ifMtu": int(mtu)
            }]
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

        encoded_ifname = urllib.parse.quote(ifname, safe='')
        path = f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}"
        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.SHOW.INTERFACE,
            driver=self.name
        )
    
    def _build_show_interfaces(self, mount: str) -> RequestSpec:
        path = f"{mount}/huawei-ifm:ifm/interfaces?content=config"
        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.SHOW.INTERFACES,
            driver=self.name
        )


    # ===== New Unified Methods (Driver Factory Pattern) =====
    
    def configure_interface(self, device: DeviceProfile, config: InterfaceConfig) -> RequestSpec:
        """
        Configure interface from Unified InterfaceConfig -> huawei-ifm payload
        Uses PATCH method for safe config merge (RFC-8040 compliant)
        
        Args:
            device: Device profile
            config: Unified interface configuration
            
        Returns:
            RequestSpec with Huawei-native payload
        """
        mount = odl_mount_base(device.node_id)
        encoded_ifname = urllib.parse.quote(config.name, safe='')
        path = f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}"
        
        # Build base payload
        interface_payload = {
            "ifName": config.name,
            "ifAdminStatus": "up" if config.enabled else "down",
        }
        
        # Add IPv4 if specified (VRP8 huawei-ip:ipv4Config structure)
        if config.ip and config.mask:
            # แปลง mask: ถ้าเป็นตัวเลข (CIDR) ให้แปลงเป็น dotted decimal
            if config.mask.isdigit():
                netmask = _prefix_to_netmask(int(config.mask))
            else:
                netmask = config.mask
            
            interface_payload["ipv4Config"] = {
                "addrCfgType": "config",
                "am4CfgAddrs": {
                    "am4CfgAddr": [{
                        "ifIpAddr": config.ip,
                        "subnetMask": netmask,
                        "addrType": "main"
                    }]
                }
            }
        
        # Add description if specified
        if config.description:
            interface_payload["description"] = config.description
        
        # Add MTU if specified
        if config.mtu:
            interface_payload["mtu"] = config.mtu
        
        payload = {"huawei-ifm:interface": [interface_payload]}
        
        return RequestSpec(
            method="PATCH",  # Use PATCH for safe merge
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json"},
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
        encoded_ifname = urllib.parse.quote(name, safe='')
        path = f"{mount}/huawei-ifm:ifm/interfaces/interface={encoded_ifname}"
        
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
