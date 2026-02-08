"""
Huawei System Driver (VRP8)
System operations using Huawei native YANG models

YANG Models:
- huawei-system

Operations:
- Set hostname
- Show version/system info
"""
from typing import Any, Dict
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class HuaweiSystemDriver(BaseDriver):
    """
    Huawei VRP8 System Driver
    
    System configuration and status using huawei-system YANG model.
    """
    name = "huawei"

    SUPPORTED_INTENTS = {
        Intents.SYSTEM.SET_HOSTNAME,
        Intents.SHOW.VERSION,
    }

    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        mount = odl_mount_base(device.node_id)

        if intent == Intents.SYSTEM.SET_HOSTNAME:
            return self._build_set_hostname(mount, params)
        
        if intent == Intents.SHOW.VERSION:
            return self._build_show_version(mount)

        raise UnsupportedIntent(intent)

    def _build_set_hostname(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Set device hostname using huawei-system"""
        hostname = params.get("hostname")
        
        if not hostname:
            raise DriverBuildError("params require hostname")
        
        path = f"{mount}/huawei-system:system"
        
        payload = {
            "huawei-system:system": {
                "sysName": hostname
            }
        }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.SYSTEM.SET_HOSTNAME,
            driver=self.name
        )
    
    def _build_show_version(self, mount: str) -> RequestSpec:
        """Get system version info"""
        # Append ?content=config to avoid ODL codec issues
        path = f"{mount}/huawei-system:system?content=config"

        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.VERSION,
            driver=self.name
        )
