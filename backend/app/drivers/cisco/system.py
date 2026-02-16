"""
Cisco System Driver
รองรับ System operations สำหรับ Cisco devices
"""
from typing import Any, Dict
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class CiscoSystemDriver(BaseDriver):
    name = "cisco"

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

        raise UnsupportedIntent(intent)

    # ===== Builder Methods =====
    
    def _build_show_running_config(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Get running configuration - Cisco IOS-XE native model"""
        section = params.get("section")
        
        # Cisco IOS-XE uses Cisco-IOS-XE-native module
        if section == "interfaces":
            path = f"{mount}/Cisco-IOS-XE-native:native/interface"
        elif section == "routing":
            path = f"{mount}/Cisco-IOS-XE-native:native/ip/route"
        elif section == "hostname":
            path = f"{mount}/Cisco-IOS-XE-native:native/hostname"
        else:
            # ดึงทั้งหมด
            path = f"{mount}/Cisco-IOS-XE-native:native"
        
        return RequestSpec(
            method="GET",
            datastore="config",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.RUNNING_CONFIG,
            driver=self.name
        )
    
    def _build_show_version(self, mount: str) -> RequestSpec:
        """Get device version info"""
        # Cisco IOS-XE version info
        path = f"{mount}/Cisco-IOS-XE-native:native/version"
        
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
        
        path = f"{mount}/Cisco-IOS-XE-native:native/hostname"
        payload = {
            "Cisco-IOS-XE-native:hostname": hostname
        }
        
        return RequestSpec(
            method="PUT",
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
        
        path = f"{mount}/Cisco-IOS-XE-native:native/ntp/Cisco-IOS-XE-ntp:server/server-list={server}"
        payload = {
            "Cisco-IOS-XE-ntp:server-list": {
                "ip-address": server
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
