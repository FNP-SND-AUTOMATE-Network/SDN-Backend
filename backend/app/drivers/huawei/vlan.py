"""
Huawei VLAN Driver (VRP8)
L2 VLAN operations using huawei-vlan YANG model

YANG Module: huawei-vlan
URL Template: /huawei-vlan:vlan/vlans/vlan
"""
from typing import Any, Dict
import urllib.parse
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class HuaweiVlanDriver(BaseDriver):
    """
    Huawei VRP8 VLAN Driver
    
    L2 VLAN configuration using huawei-vlan YANG model.
    """
    name = "huawei"

    SUPPORTED_INTENTS = {
        Intents.VLAN.CREATE,
        Intents.VLAN.DELETE,
        Intents.VLAN.UPDATE,
        Intents.SHOW.VLANS,
    }

    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        mount = odl_mount_base(device.node_id)

        if intent == Intents.VLAN.CREATE:
            return self._build_vlan_create(mount, params)
        
        if intent == Intents.VLAN.DELETE:
            return self._build_vlan_delete(mount, params)
        
        if intent == Intents.VLAN.UPDATE:
            return self._build_vlan_update(mount, params)
        
        if intent == Intents.SHOW.VLANS:
            return self._build_show_vlans(mount)

        raise UnsupportedIntent(intent)

    def _build_vlan_create(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Create VLAN using huawei-vlan module.
        
        VRP8 YANG Path: /huawei-vlan:vlan/vlans/vlan
        
        Params:
            vlan_id: VLAN ID (integer, e.g., 10)
            name: VLAN name (optional)
            description: VLAN description (optional)
        """
        vlan_id = params.get("vlan_id")
        name = params.get("name", f"VLAN{vlan_id}")
        description = params.get("description", "")
        
        if not vlan_id:
            raise DriverBuildError("params require vlan_id")
        
        path = f"{mount}/huawei-vlan:vlan/vlans/vlan={vlan_id}"
        
        payload = {
            "huawei-vlan:vlan": [{
                "id": int(vlan_id),
                "name": name
            }]
        }
        
        if description:
            payload["huawei-vlan:vlan"][0]["description"] = description

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.VLAN.CREATE,
            driver=self.name
        )
    
    def _build_vlan_delete(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Delete VLAN"""
        vlan_id = params.get("vlan_id")
        
        if not vlan_id:
            raise DriverBuildError("params require vlan_id")
        
        path = f"{mount}/huawei-vlan:vlan/vlans/vlan={vlan_id}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.VLAN.DELETE,
            driver=self.name
        )
    
    def _build_vlan_update(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Update VLAN attributes"""
        vlan_id = params.get("vlan_id")
        name = params.get("name")
        description = params.get("description")
        
        if not vlan_id:
            raise DriverBuildError("params require vlan_id")
        
        path = f"{mount}/huawei-vlan:vlan/vlans/vlan={vlan_id}"
        
        vlan_config = {"id": int(vlan_id)}
        if name:
            vlan_config["name"] = name
        if description:
            vlan_config["description"] = description
        
        payload = {
            "huawei-vlan:vlan": [vlan_config]
        }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.VLAN.UPDATE,
            driver=self.name
        )
    
    def _build_show_vlans(self, mount: str) -> RequestSpec:
        """Get all VLANs"""
        path = f"{mount}/huawei-vlan:vlan/vlans?content=config"

        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.VLANS,
            driver=self.name
        )
