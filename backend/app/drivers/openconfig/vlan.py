"""
OpenConfig VLAN Driver
รองรับ OpenConfig YANG models สำหรับ VLAN operations
"""
from typing import Any, Dict
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class OpenConfigVlanDriver(BaseDriver):
    name = "openconfig"

    # Intents ที่ driver นี้รองรับ
    SUPPORTED_INTENTS = {
        Intents.VLAN.CREATE,
        Intents.VLAN.DELETE,
        Intents.VLAN.ASSIGN_PORT,
    }

    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        mount = odl_mount_base(device.node_id)

        # ===== VLAN CREATE =====
        if intent == Intents.VLAN.CREATE:
            return self._build_create_vlan(mount, params)
        
        # ===== VLAN DELETE =====
        if intent == Intents.VLAN.DELETE:
            return self._build_delete_vlan(mount, params)
        
        # ===== VLAN ASSIGN PORT =====
        if intent == Intents.VLAN.ASSIGN_PORT:
            return self._build_assign_port(mount, params)

        raise UnsupportedIntent(intent)

    # ===== Builder Methods =====
    
    def _build_create_vlan(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Create VLAN using OpenConfig network-instance YANG model
        
        OpenConfig uses network-instance for L2 VLANs
        Path: /openconfig-network-instance:network-instances/network-instance={vlan_name}/vlans/vlan={vlan_id}
        """
        vlan_id = params.get("vlan_id")
        name = params.get("name", f"VLAN{vlan_id}")
        
        if not vlan_id:
            raise DriverBuildError("params require vlan_id")

        # OpenConfig VLAN path
        path = f"{mount}/openconfig-network-instance:network-instances/network-instance=default/vlans/vlan={vlan_id}"

        payload = {
            "openconfig-network-instance:vlan": {
                "vlan-id": int(vlan_id),
                "config": {
                    "vlan-id": int(vlan_id),
                    "name": name,
                    "status": "ACTIVE"
                }
            }
        }

        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json"},
            intent=Intents.VLAN.CREATE,
            driver=self.name
        )

    def _build_delete_vlan(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Delete VLAN using OpenConfig network-instance YANG model
        
        Path: DELETE /openconfig-network-instance:network-instances/network-instance=default/vlans/vlan={vlan_id}
        """
        vlan_id = params.get("vlan_id")
        
        if not vlan_id:
            raise DriverBuildError("params require vlan_id")

        path = f"{mount}/openconfig-network-instance:network-instances/network-instance=default/vlans/vlan={vlan_id}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.VLAN.DELETE,
            driver=self.name
        )

    def _build_assign_port(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Assign port to VLAN using OpenConfig interfaces YANG model
        
        OpenConfig uses ethernet/switched-vlan for switchport configuration
        
        Supports:
        - mode: "access" (default) - ACCESS mode with access vlan
        - mode: "trunk" - TRUNK mode with trunk vlans
        
        Path: /openconfig-interfaces:interfaces/interface={interface}/openconfig-if-ethernet:ethernet/openconfig-vlan:switched-vlan
        """
        interface = params.get("interface")
        vlan_id = params.get("vlan_id")
        mode = params.get("mode", "access")  # access or trunk
        
        if not interface or not vlan_id:
            raise DriverBuildError("params require interface, vlan_id")

        path = (
            f"{mount}/openconfig-interfaces:interfaces/interface={interface}"
            f"/openconfig-if-ethernet:ethernet/openconfig-vlan:switched-vlan/config"
        )

        if mode == "trunk":
            payload = {
                "openconfig-vlan:config": {
                    "interface-mode": "TRUNK",
                    "trunk-vlans": [int(vlan_id)]
                }
            }
        else:
            # Access mode (default)
            payload = {
                "openconfig-vlan:config": {
                    "interface-mode": "ACCESS",
                    "access-vlan": int(vlan_id)
                }
            }

        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json"},
            intent=Intents.VLAN.ASSIGN_PORT,
            driver=self.name
        )
