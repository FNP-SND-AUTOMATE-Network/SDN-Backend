"""
OpenConfig System Driver
รองรับ System operations เช่น hostname, running-config, version
"""
from typing import Any, Dict
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class OpenConfigSystemDriver(BaseDriver):
    name = "openconfig"

    SUPPORTED_INTENTS = {
        Intents.SHOW.RUNNING_CONFIG,
        Intents.SHOW.VERSION,
        Intents.SYSTEM.SET_HOSTNAME,
        Intents.SYSTEM.SET_NTP,
        Intents.SYSTEM.SET_DNS,
    }

    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        mount = odl_mount_base(device.node_id)

        # ===== SHOW RUNNING CONFIG =====
        if intent == Intents.SHOW.RUNNING_CONFIG:
            return self._build_show_running_config(mount, params)
        
        # ===== SHOW VERSION =====
        if intent == Intents.SHOW.VERSION:
            return self._build_show_version(mount)
        
        # ===== SYSTEM SET HOSTNAME =====
        if intent == Intents.SYSTEM.SET_HOSTNAME:
            return self._build_set_hostname(mount, params)
        
        # ===== SYSTEM SET NTP =====
        if intent == Intents.SYSTEM.SET_NTP:
            return self._build_set_ntp(mount, params)
        
        # ===== SYSTEM SET DNS =====
        if intent == Intents.SYSTEM.SET_DNS:
            return self._build_set_dns(mount, params)

        raise UnsupportedIntent(intent)

    # ===== Builder Methods =====
    
    def _build_show_running_config(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Get running configuration from device"""
        section = params.get("section")
        
        # OpenConfig ไม่มี running-config โดยตรง
        # ดึงจาก config datastore แทน
        if section == "interfaces":
            path = f"{mount}/openconfig-interfaces:interfaces"
        elif section == "system":
            path = f"{mount}/openconfig-system:system"
        elif section == "routing":
            path = f"{mount}/openconfig-network-instance:network-instances"
        else:
            # ดึงทั้งหมด - ใช้ root config
            path = f"{mount}"
        
        return RequestSpec(
            method="GET",
            datastore="config",  # config datastore = running-config
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.RUNNING_CONFIG,
            driver=self.name
        )
    
    def _build_show_version(self, mount: str) -> RequestSpec:
        """Get system version/info"""
        path = f"{mount}/openconfig-system:system/state"
        
        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.VERSION,
            driver=self.name
        )
    
    def _build_set_hostname(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        hostname = params.get("hostname")
        if not hostname:
            raise DriverBuildError("params require hostname")
        
        path = f"{mount}/openconfig-system:system/config"
        payload = {
            "openconfig-system:config": {
                "hostname": hostname
            }
        }
        
        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.SYSTEM.SET_HOSTNAME,
            driver=self.name
        )
    
    def _build_set_ntp(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        server = params.get("server")
        if not server:
            raise DriverBuildError("params require server")
        
        prefer = params.get("prefer", False)
        
        path = f"{mount}/openconfig-system:system/ntp/servers/server={server}"
        payload = {
            "openconfig-system:server": {
                "address": server,
                "config": {
                    "address": server,
                    "prefer": prefer
                }
            }
        }
        
        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.SYSTEM.SET_NTP,
            driver=self.name
        )
    
    def _build_set_dns(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        server = params.get("server")
        if not server:
            raise DriverBuildError("params require server")
        
        domain = params.get("domain")
        
        path = f"{mount}/openconfig-system:system/dns/servers/server={server}"
        payload = {
            "openconfig-system:server": {
                "address": server,
                "config": {
                    "address": server
                }
            }
        }
        
        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.SYSTEM.SET_DNS,
            driver=self.name
        )
