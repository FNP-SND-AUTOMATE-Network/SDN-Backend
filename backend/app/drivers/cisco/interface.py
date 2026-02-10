"""
Cisco Interface Driver (Native IOS-XE YANG)
รองรับ Cisco-IOS-XE-native YANG model สำหรับ Interface operations

All operations use Cisco-IOS-XE-native:native/interface path
NO IETF models - pure Native IOS-XE only

Path format: .../Cisco-IOS-XE-native:native/interface/{Type}={Number}
Payload key: Cisco-IOS-XE-native:{Type}
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

    @staticmethod
    def _parse_interface_name(ifname: str):
        """
        Parse interface name into type and number
        e.g. 'GigabitEthernet2' -> ('GigabitEthernet', '2')
             'GigabitEthernet0/0/0' -> ('GigabitEthernet', '0/0/0')
             'Loopback0' -> ('Loopback', '0')
        """
        import re
        match = re.match(r'^([A-Za-z\-]+?)(\d.*)$', ifname)
        if match:
            return match.group(1), match.group(2)
        return ifname, ""

    @staticmethod
    def _encode_interface_number(number: str) -> str:
        """
        Encode interface number for URL path
        RFC-8040: / in list key must be encoded as %2F
        """
        return number.replace("/", "%2F")

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

    # ===== Builder Methods (All Native IOS-XE) =====
    
    def _build_set_ipv4(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Set IPv4 address using Cisco-IOS-XE-native YANG model
        
        Path: .../Cisco-IOS-XE-native:native/interface/{Type}={Number}
        Payload: ip.address.primary.address + mask
        """
        ifname = params.get("interface")
        ip = params.get("ip")
        prefix = params.get("prefix")
        if not ifname or not ip or prefix is None:
            raise DriverBuildError("params require interface, ip, prefix")

        netmask = _prefix_to_netmask(int(prefix))
        iface_type, iface_num = self._parse_interface_name(ifname)
        encoded_num = self._encode_interface_number(iface_num)
        
        path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"

        payload = {
            f"Cisco-IOS-XE-native:{iface_type}": [{
                "name": iface_num,
                "ip": {
                    "address": {
                        "primary": {
                            "address": ip,
                            "mask": netmask
                        }
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
            intent=Intents.INTERFACE.SET_IPV4,
            driver=self.name
        )
    
    def _build_remove_ipv4(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Remove IPv4 address from interface using native model"""
        ifname = params.get("interface")
        if not ifname:
            raise DriverBuildError("params require interface")

        iface_type, iface_num = self._parse_interface_name(ifname)
        encoded_num = self._encode_interface_number(iface_num)

        ip = params.get("ip")
        
        if ip:
            # DELETE specific IP address (primary)
            path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}/ip/address/primary"
        else:
            # DELETE all IP config from interface
            path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}/ip/address"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.INTERFACE.REMOVE_IPV4,
            driver=self.name
        )

    def _build_set_ipv6(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Set IPv6 address using Cisco-IOS-XE-native YANG model
        
        Path: .../Cisco-IOS-XE-native:native/interface/{Type}={Number}
        Payload: ipv6.address.prefix-list
        """
        ifname = params.get("interface")
        ip = params.get("ip")
        prefix = params.get("prefix")
        if not ifname or not ip or prefix is None:
            raise DriverBuildError("params require interface, ip, prefix")

        iface_type, iface_num = self._parse_interface_name(ifname)
        encoded_num = self._encode_interface_number(iface_num)
        
        path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"

        payload = {
            f"Cisco-IOS-XE-native:{iface_type}": [{
                "name": iface_num,
                "ipv6": {
                    "address": {
                        "prefix-list": [{
                            "prefix": f"{ip}/{prefix}"
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
    
    def _build_remove_ipv6(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Remove IPv6 address from interface using native model"""
        ifname = params.get("interface")
        if not ifname:
            raise DriverBuildError("params require interface")

        iface_type, iface_num = self._parse_interface_name(ifname)
        encoded_num = self._encode_interface_number(iface_num)

        ip = params.get("ip")
        prefix = params.get("prefix")
        
        if ip and prefix:
            # DELETE specific IPv6 prefix
            path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}/ipv6/address/prefix-list={ip}%2F{prefix}"
        else:
            # DELETE all IPv6 config from interface
            path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}/ipv6/address"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.INTERFACE.REMOVE_IPV6,
            driver=self.name
        )

    def _build_enable(self, mount: str, params: Dict[str, Any], enabled: bool) -> RequestSpec:
        """
        Enable/Disable interface using Cisco-IOS-XE-native YANG model
        
        Enable (no shutdown): DELETE the shutdown leaf
        Disable (shutdown): PATCH with shutdown: [null]
        """
        ifname = params.get("interface")
        if not ifname:
            raise DriverBuildError("params require interface")

        iface_type, iface_num = self._parse_interface_name(ifname)
        encoded_num = self._encode_interface_number(iface_num)
        
        if enabled:
            # Enable = DELETE the shutdown leaf (no shutdown)
            path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}/shutdown"
            return RequestSpec(
                method="DELETE",
                datastore="config",
                path=path,
                payload=None,
                headers={"Accept": "application/yang-data+json"},
                intent=Intents.INTERFACE.ENABLE,
                driver=self.name
            )
        else:
            # Disable = PATCH to add shutdown
            path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"
            payload = {
                f"Cisco-IOS-XE-native:{iface_type}": [{
                    "name": iface_num,
                    "shutdown": [None]
                }]
            }
            return RequestSpec(
                method="PATCH",
                datastore="config",
                path=path,
                payload=payload,
                headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
                intent=Intents.INTERFACE.DISABLE,
                driver=self.name
            )
    
    def _build_set_description(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Set description using Cisco-IOS-XE-native YANG model"""
        ifname = params.get("interface")
        description = params.get("description", "")
        if not ifname:
            raise DriverBuildError("params require interface")

        iface_type, iface_num = self._parse_interface_name(ifname)
        encoded_num = self._encode_interface_number(iface_num)

        path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"
        payload = {
            f"Cisco-IOS-XE-native:{iface_type}": [{
                "name": iface_num,
                "description": description
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
        """Set MTU using Cisco-IOS-XE-native YANG model"""
        ifname = params.get("interface")
        mtu = params.get("mtu")
        if not ifname or mtu is None:
            raise DriverBuildError("params require interface, mtu")

        iface_type, iface_num = self._parse_interface_name(ifname)
        encoded_num = self._encode_interface_number(iface_num)

        path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"
        payload = {
            f"Cisco-IOS-XE-native:{iface_type}": [{
                "name": iface_num,
                "ip": {
                    "mtu": int(mtu)
                }
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
        """Get single interface using Cisco-IOS-XE-native YANG model"""
        ifname = params.get("interface")
        if not ifname:
            raise DriverBuildError("params require interface")

        iface_type, iface_num = self._parse_interface_name(ifname)
        encoded_num = self._encode_interface_number(iface_num)

        path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"
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
        """Get all interfaces using Cisco-IOS-XE-native YANG model"""
        path = f"{mount}/Cisco-IOS-XE-native:native/interface"
        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.SHOW.INTERFACES,
            driver=self.name
        )


    # ===== Unified Methods (Driver Factory Pattern) =====
    
    def configure_interface(self, device: DeviceProfile, config: InterfaceConfig) -> RequestSpec:
        """
        Configure interface from Unified InterfaceConfig -> Cisco-IOS-XE-native payload
        Uses PATCH method for safe config merge (RFC-8040 compliant)
        """
        mount = odl_mount_base(device.node_id)
        iface_type, iface_num = self._parse_interface_name(config.name)
        encoded_num = self._encode_interface_number(iface_num)
        
        path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"
        
        # Build base payload
        interface_payload = {
            "name": iface_num,
        }
        
        # Add IPv4 if specified
        if config.ip and config.mask:
            if config.mask.isdigit():
                netmask = _prefix_to_netmask(int(config.mask))
            else:
                netmask = config.mask
            
            interface_payload["ip"] = {
                "address": {
                    "primary": {
                        "address": config.ip,
                        "mask": netmask
                    }
                }
            }
        
        # Add description if specified
        if config.description:
            interface_payload["description"] = config.description
        
        # Add MTU if specified
        if config.mtu:
            interface_payload["mtu"] = config.mtu
        
        # Add shutdown if disabled
        if not config.enabled:
            interface_payload["shutdown"] = [None]
        
        payload = {f"Cisco-IOS-XE-native:{iface_type}": [interface_payload]}
        
        return RequestSpec(
            method="PATCH",
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
        Uses Cisco-IOS-XE-native path
        """
        mount = odl_mount_base(device.node_id)
        iface_type, iface_num = self._parse_interface_name(name)
        encoded_num = self._encode_interface_number(iface_num)

        path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"
        
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
