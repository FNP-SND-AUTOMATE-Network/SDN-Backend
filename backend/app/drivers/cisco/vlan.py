"""
Cisco VLAN Driver
รองรับ Cisco IOS-XE YANG models สำหรับ VLAN operations
"""
from typing import Any, Dict
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class CiscoVlanDriver(BaseDriver):
    name = "cisco"

    SUPPORTED_INTENTS = {
        Intents.VLAN.CREATE,
        Intents.VLAN.DELETE,
        Intents.VLAN.UPDATE,
        Intents.VLAN.ASSIGN_PORT,
        Intents.SHOW.VLANS,
    }

    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        mount = odl_mount_base(device.node_id)

        # ===== VLAN CREATE =====
        if intent == Intents.VLAN.CREATE:
            return self._build_create_vlan(mount, params)
        
        # ===== VLAN DELETE =====
        if intent == Intents.VLAN.DELETE:
            return self._build_delete_vlan(mount, params)
        
        # ===== VLAN UPDATE =====
        if intent == Intents.VLAN.UPDATE:
            return self._build_update_vlan(mount, params)
        
        # ===== VLAN ASSIGN PORT =====
        if intent == Intents.VLAN.ASSIGN_PORT:
            return self._build_assign_port(mount, params)
        
        # ===== SHOW VLANS =====
        if intent == Intents.SHOW.VLANS:
            return self._build_show_vlans(mount)

        raise UnsupportedIntent(intent)

    # ===== Builder Methods =====
    
    def _build_create_vlan(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Create VLAN using Cisco IOS-XE native YANG model
        
        Path: /native/vlan/vlan-list={vlan_id}
        """
        vlan_id = params.get("vlan_id")
        name = params.get("name", f"VLAN{vlan_id}")
        
        if not vlan_id:
            raise DriverBuildError("params require vlan_id")

        path = f"{mount}/Cisco-IOS-XE-native:native/vlan/Cisco-IOS-XE-vlan:vlan-list={vlan_id}"

        payload = {
            "Cisco-IOS-XE-vlan:vlan-list": {
                "id": int(vlan_id),
                "name": name
            }
        }

        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.VLAN.CREATE,
            driver=self.name
        )

    def _build_delete_vlan(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Delete VLAN using Cisco IOS-XE native YANG model
        
        Path: DELETE /native/vlan/vlan-list={vlan_id}
        """
        vlan_id = params.get("vlan_id")
        
        if not vlan_id:
            raise DriverBuildError("params require vlan_id")

        path = f"{mount}/Cisco-IOS-XE-native:native/vlan/Cisco-IOS-XE-vlan:vlan-list={vlan_id}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.VLAN.DELETE,
            driver=self.name
        )

    def _build_update_vlan(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Update VLAN name/description using PATCH
        
        Path: PATCH /native/vlan/vlan-list={vlan_id}
        """
        vlan_id = params.get("vlan_id")
        if not vlan_id:
            raise DriverBuildError("params require vlan_id")

        path = f"{mount}/Cisco-IOS-XE-native:native/vlan/Cisco-IOS-XE-vlan:vlan-list={vlan_id}"

        vlan_data = {"id": int(vlan_id)}
        if params.get("name"):
            vlan_data["name"] = params["name"]

        payload = {
            "Cisco-IOS-XE-vlan:vlan-list": vlan_data
        }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.VLAN.UPDATE,
            driver=self.name
        )

    def _build_show_vlans(self, mount: str) -> RequestSpec:
        """Get all VLANs from device"""
        path = f"{mount}/Cisco-IOS-XE-native:native/vlan"

        return RequestSpec(
            method="GET",
            datastore="config",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.VLANS,
            driver=self.name
        )

    def _build_assign_port(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Assign port to VLAN using Cisco IOS-XE native YANG model
        
        Supports:
        - mode: "access" (default) - switchport mode access + access vlan
        - mode: "trunk" - switchport mode trunk + trunk allowed vlan
        
        Path: /native/interface/GigabitEthernet={port_number}
        """
        interface = params.get("interface")
        vlan_id = params.get("vlan_id")
        mode = params.get("mode", "access")  # access or trunk
        
        if not interface or not vlan_id:
            raise DriverBuildError("params require interface, vlan_id")

        # Parse interface name (e.g., "GigabitEthernet0/1" -> type="GigabitEthernet", number="0/1")
        if_type, if_number = self._parse_interface_name(interface)
        
        path = f"{mount}/Cisco-IOS-XE-native:native/interface/{if_type}={self._encode_interface_number(if_number)}"

        if mode == "trunk":
            payload = {
                f"Cisco-IOS-XE-native:{if_type}": {
                    "name": if_number,
                    "switchport": {
                        "Cisco-IOS-XE-switch:mode": {
                            "trunk": {}
                        },
                        "Cisco-IOS-XE-switch:trunk": {
                            "allowed": {
                                "vlan": {
                                    "vlans": str(vlan_id)
                                }
                            }
                        }
                    }
                }
            }
        else:
            # Access mode (default)
            payload = {
                f"Cisco-IOS-XE-native:{if_type}": {
                    "name": if_number,
                    "switchport": {
                        "Cisco-IOS-XE-switch:mode": {
                            "access": {}
                        },
                        "Cisco-IOS-XE-switch:access": {
                            "vlan": {
                                "vlan": int(vlan_id)
                            }
                        }
                    }
                }
            }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.VLAN.ASSIGN_PORT,
            driver=self.name
        )

    def _parse_interface_name(self, interface: str) -> tuple:
        """
        Parse interface name into type and number
        
        Examples:
        - "GigabitEthernet0/1" -> ("GigabitEthernet", "0/1")
        - "FastEthernet0/0/1" -> ("FastEthernet", "0/0/1")
        - "Ethernet1/0" -> ("Ethernet", "1/0")
        """
        import re
        match = re.match(r'^([A-Za-z]+)(.+)$', interface)
        if not match:
            raise DriverBuildError(f"Invalid interface name: {interface}")
        return match.group(1), match.group(2)

    def _encode_interface_number(self, number: str) -> str:
        """
        Encode interface number for URL path
        
        RFC-8040: / in list key must be encoded as %2F
        """
        return number.replace("/", "%2F")
