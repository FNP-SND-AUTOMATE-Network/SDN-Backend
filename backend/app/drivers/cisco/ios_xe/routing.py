"""
Cisco Routing Driver
รองรับ Routing operations สำหรับ Cisco IOS-XE devices
"""
import os
import requests
from requests.auth import HTTPBasicAuth
from typing import Any, Dict
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class CiscoRoutingDriver(BaseDriver):
    name = "cisco"

    @staticmethod
    def _parse_interface_name(ifname: str):
        """Parse interface name into type and number"""
        import re
        match = re.match(r'^([A-Za-z\-]+?)(\d.*)$', ifname)
        if match:
            return match.group(1), match.group(2)
        return ifname, ""

    @staticmethod
    def _encode_interface_number(number: str) -> str:
        """RFC-8040: / in list key must be encoded as %2F"""
        return number.replace("/", "%2F")

    SUPPORTED_INTENTS = {
        Intents.ROUTING.STATIC_ADD,
        Intents.ROUTING.STATIC_DELETE,
        Intents.ROUTING.DEFAULT_ADD,
        Intents.ROUTING.DEFAULT_DELETE,
        Intents.SHOW.IP_ROUTE,
        Intents.SHOW.IP_INTERFACE_BRIEF,
        # OSPF
        Intents.ROUTING.OSPF_ENABLE,
        Intents.ROUTING.OSPF_DISABLE,
        Intents.ROUTING.OSPF_ADD_NETWORK,
        Intents.ROUTING.OSPF_ADD_NETWORK_INTERFACE,
        Intents.ROUTING.OSPF_REMOVE_NETWORK_INTERFACE,
        Intents.ROUTING.OSPF_SET_ROUTER_ID,
        Intents.ROUTING.OSPF_SET_PASSIVE_INTERFACE,
        Intents.ROUTING.OSPF_REMOVE_PASSIVE_INTERFACE,
        Intents.SHOW.OSPF_NEIGHBORS,
        Intents.SHOW.OSPF_DATABASE,
    }

    def _fetch_device_version(self, mount: str) -> str:
        """
        ยิง GET ไปที่ OpenDaylight เพื่อเช็ค OS Version ของอุปกรณ์แบบ Real-time
        โดยดึงการตั้งค่า (IP, Auth, Timeout) จากไฟล์ .env
        """
        # 1. ดึงค่าจาก Environment Variables (พร้อมกำหนดค่า Default เผื่อหาไฟล์ .env ไม่เจอ)
        odl_base_url = os.getenv("ODL_BASE_URL", "http://192.168.1.37:8181").rstrip('/')
        odl_user = os.getenv("ODL_USERNAME", "admin")
        odl_pass = os.getenv("ODL_PASSWORD", "admin")
        odl_timeout = int(os.getenv("ODL_TIMEOUT_SEC", 10))
        
        # 2. จัดรูปแบบ URL ให้สมบูรณ์
        if not mount.startswith("http"):
            # ป้องกันกรณี mount ไม่มี / นำหน้า
            mount_path = mount if mount.startswith("/") else f"/{mount}"
            url = f"{odl_base_url}{mount_path}/Cisco-IOS-XE-native:native/version"
        else:
            url = f"{mount}/Cisco-IOS-XE-native:native/version"
            
        headers = {"Accept": "application/yang-data+json"}
        
        try:
            print(f"\n[DEBUG-OSPF] ยิงเช็คเวอร์ชันไปที่: {url}")
            
            # 3. ใช้ค่าที่ดึงมาจาก .env ทั้งหมดในการยิง Request
            response = requests.get(
                url, 
                headers=headers, 
                auth=HTTPBasicAuth(odl_user, odl_pass),
                timeout=odl_timeout 
            )
            
            if response.status_code == 200:
                data = response.json()
                version = data.get("Cisco-IOS-XE-native:version")
                if version:
                    print(f"[DEBUG-OSPF] ✔️ ดึงเวอร์ชันสำเร็จ! อุปกรณ์นี้คือเวอร์ชัน: {version}\n")
                    return str(version)
            else:
                print(f"[DEBUG-OSPF] ❌ ยิงเช็คเวอร์ชันไม่ผ่าน Status: {response.status_code}, Body: {response.text}\n")
                
        except requests.exceptions.RequestException as e:
            # ดักจับ Error จากฝั่ง Network (เช่น Timeout, Connection Refused)
            print(f"\n[DEBUG-OSPF] 💥 เกิดข้อผิดพลาดด้านเครือข่ายตอนดึงเวอร์ชัน: {e}\n")
            
        # 4. หากมีปัญหาใดๆ จะ Fallback กลับไปที่โครงสร้างของเวอร์ชัน 16 (เพื่อให้ระบบพยายามทำงานต่อ)
        print("[DEBUG-OSPF] ⚠️ ไม่สามารถดึงเวอร์ชันได้ ระบบจะใช้ Default (v16)")
        return "16."

    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        mount = odl_mount_base(device.node_id)

        # ===== ROUTING STATIC ADD =====
        if intent == Intents.ROUTING.STATIC_ADD:
            return self._build_static_add(mount, params)
        
        # ===== ROUTING STATIC DELETE =====
        if intent == Intents.ROUTING.STATIC_DELETE:
            return self._build_static_delete(mount, params)
        
        # ===== ROUTING DEFAULT ADD =====
        if intent == Intents.ROUTING.DEFAULT_ADD:
            return self._build_default_add(mount, params)
        
        # ===== ROUTING DEFAULT DELETE =====
        if intent == Intents.ROUTING.DEFAULT_DELETE:
            return self._build_default_delete(mount, params)
        
        # ===== SHOW IP ROUTE =====
        if intent == Intents.SHOW.IP_ROUTE:
            return self._build_show_ip_route(mount, params)
        
        # ===== SHOW IP INTERFACE BRIEF =====
        if intent == Intents.SHOW.IP_INTERFACE_BRIEF:
            return self._build_show_ip_interface_brief(mount)
        
        # ===== OSPF INTENTS =====
        if intent == Intents.ROUTING.OSPF_ENABLE:
            return self._build_ospf_enable(mount, params)
        
        if intent == Intents.ROUTING.OSPF_DISABLE:
            return self._build_ospf_disable(mount, params)
        
        if intent == Intents.ROUTING.OSPF_ADD_NETWORK:
            return self._build_ospf_add_network(mount, params)
        
        if intent == Intents.ROUTING.OSPF_ADD_NETWORK_INTERFACE:
            return self._build_ospf_add_network_interface(mount, params)
        
        if intent == Intents.ROUTING.OSPF_REMOVE_NETWORK_INTERFACE:
            return self._build_ospf_remove_network_interface(mount, params)
        
        if intent == Intents.ROUTING.OSPF_SET_ROUTER_ID:
            return self._build_ospf_set_router_id(mount, params)
        
        if intent == Intents.ROUTING.OSPF_SET_PASSIVE_INTERFACE:
            return self._build_ospf_set_passive_interface(mount, params)
        
        if intent == Intents.ROUTING.OSPF_REMOVE_PASSIVE_INTERFACE:
            return self._build_ospf_remove_passive_interface(mount, params)
        
        if intent == Intents.SHOW.OSPF_NEIGHBORS:
            return self._build_show_ospf_neighbors(mount, params)
        
        if intent == Intents.SHOW.OSPF_DATABASE:
            return self._build_show_ospf_database(mount, params)

        raise UnsupportedIntent(intent, os_type=device.os_type)

    # ===== Builder Methods =====
    
    def _build_static_add(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Add static route using Cisco IOS-XE native model"""
        prefix = params.get("prefix")
        next_hop = params.get("next_hop")
        
        if not prefix or not next_hop:
            raise DriverBuildError("params require prefix, next_hop")
        
        # แยก prefix และ mask
        if "/" in prefix:
            network, prefix_len = prefix.split("/")
            mask = _prefix_to_netmask(int(prefix_len))
        else:
            network = prefix
            mask = params.get("mask", "255.255.255.0")
        
        # Cisco IOS-XE static route path
        path = (
            f"{mount}/Cisco-IOS-XE-native:native/ip/route"
            f"/ip-route-interface-forwarding-list={network},{mask}"
        )
        
        payload = {
            "Cisco-IOS-XE-native:ip-route-interface-forwarding-list": {
                "prefix": network,
                "mask": mask,
                "fwd-list": [{
                    "fwd": next_hop
                }]
            }
        }

        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.ROUTING.STATIC_ADD,
            driver=self.name
        )
    
    def _build_static_delete(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Delete static route"""
        prefix = params.get("prefix")
        
        if not prefix:
            raise DriverBuildError("params require prefix")
        
        if "/" in prefix:
            network, prefix_len = prefix.split("/")
            mask = _prefix_to_netmask(int(prefix_len))
        else:
            network = prefix
            mask = params.get("mask", "255.255.255.0")
        
        path = (
            f"{mount}/Cisco-IOS-XE-native:native/ip/route"
            f"/ip-route-interface-forwarding-list={network},{mask}"
        )

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.ROUTING.STATIC_DELETE,
            driver=self.name
        )
    
    def _build_default_add(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Add default route (0.0.0.0/0)"""
        next_hop = params.get("next_hop")
        
        if not next_hop:
            raise DriverBuildError("params require next_hop")
        
        path = (
            f"{mount}/Cisco-IOS-XE-native:native/ip/route"
            f"/ip-route-interface-forwarding-list=0.0.0.0,0.0.0.0"
        )
        
        payload = {
            "Cisco-IOS-XE-native:ip-route-interface-forwarding-list": {
                "prefix": "0.0.0.0",
                "mask": "0.0.0.0",
                "fwd-list": [{
                    "fwd": next_hop
                }]
            }
        }

        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.ROUTING.DEFAULT_ADD,
            driver=self.name
        )
    
    def _build_default_delete(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Delete default route"""
        path = (
            f"{mount}/Cisco-IOS-XE-native:native/ip/route"
            f"/ip-route-interface-forwarding-list=0.0.0.0,0.0.0.0"
        )

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.ROUTING.DEFAULT_DELETE,
            driver=self.name
        )
    
    def _build_show_ip_route(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Get routing table from Cisco device"""
        # Use ietf-routing:routing-state for operational data (Active Routes)
        path = f"{mount}/ietf-routing:routing-state"

        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.IP_ROUTE,
            driver=self.name
        )
    
    def _build_show_ip_interface_brief(self, mount: str) -> RequestSpec:
        """Get IP interface brief (summary view) using native model"""
        # Use native model for consistency
        path = f"{mount}/Cisco-IOS-XE-native:native/interface"

        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.IP_INTERFACE_BRIEF,
            driver=self.name
        )

 # ===== OSPF Methods =====
    
    def _build_ospf_add_network(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        process_id = params.get("process_id")
        network = params.get("network")
        wildcard = params.get("wildcard_mask") or params.get("wildcard")
        area = params.get("area")
        
        if process_id is None or not network or not wildcard or area is None:
            raise DriverBuildError("params require process_id, network, wildcard_mask, area")
        
        path = f"{mount}/Cisco-IOS-XE-native:native/router"
        device_version = self._fetch_device_version(mount)
        
        if device_version.startswith("16."):
            # V16: ใช้ ospf ตรงๆ และใช้ mask
            payload = {
                "Cisco-IOS-XE-native:router": {
                    "Cisco-IOS-XE-ospf:ospf": [{
                        "id": int(process_id),
                        "network": [{
                            "ip": network,
                            "mask": wildcard,
                            "area": int(area)
                        }]
                    }]
                }
            }
        else:
            # V17+: ใช้ router-ospf -> ospf -> process-id และใช้ wildcard
            payload = {
                "Cisco-IOS-XE-native:router": {
                    "Cisco-IOS-XE-ospf:router-ospf": {
                        "ospf": {
                            "process-id": [{
                                "id": int(process_id),
                                "network": [{
                                    "ip": network,
                                    "wildcard": wildcard,
                                    "area": int(area)
                                }]
                            }]
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
            intent=Intents.ROUTING.OSPF_ADD_NETWORK,
            driver=self.name
        )
    
    def _build_ospf_enable(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        process_id = params.get("process_id")
        router_id = params.get("router_id")
        
        if not process_id:
            raise DriverBuildError("params require process_id")
        
        path = f"{mount}/Cisco-IOS-XE-native:native/router"
        device_version = self._fetch_device_version(mount)
        
        if device_version.startswith("16."):
            ospf_entry = {"id": int(process_id)}
            if router_id: ospf_entry["router-id"] = router_id
            payload = {
                "Cisco-IOS-XE-native:router": {
                    "Cisco-IOS-XE-ospf:ospf": [ospf_entry]
                }
            }
        else:
            ospf_entry = {"id": int(process_id)}
            if router_id: ospf_entry["router-id"] = router_id
            payload = {
                "Cisco-IOS-XE-native:router": {
                    "Cisco-IOS-XE-ospf:router-ospf": {
                        "ospf": {
                            "process-id": [ospf_entry]
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
            intent=Intents.ROUTING.OSPF_ENABLE,
            driver=self.name
        )
    
    def _build_ospf_disable(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        process_id = params.get("process_id")
        if not process_id:
            raise DriverBuildError("params require process_id")
        
        device_version = self._fetch_device_version(mount)
        
        if device_version.startswith("16."):
            path = f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:ospf={process_id}"
        else:
            # V17 ต้องเจาะลึกไปที่ process-id ตาม Path ใหม่
            path = f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:router-ospf/ospf/process-id={process_id}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_DISABLE,
            driver=self.name
        )
    
    def _build_ospf_set_router_id(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        process_id = params.get("process_id")
        router_id = params.get("router_id")
        
        if not process_id or not router_id:
            raise DriverBuildError("params require process_id, router_id")
        
        path = f"{mount}/Cisco-IOS-XE-native:native/router"
        device_version = self._fetch_device_version(mount)
        
        if device_version.startswith("16."):
            payload = {
                "Cisco-IOS-XE-native:router": {
                    "Cisco-IOS-XE-ospf:ospf": [{"id": int(process_id), "router-id": router_id}]
                }
            }
        else:
            payload = {
                "Cisco-IOS-XE-native:router": {
                    "Cisco-IOS-XE-ospf:router-ospf": {
                        "ospf": {
                            "process-id": [{"id": int(process_id), "router-id": router_id}]
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
            intent=Intents.ROUTING.OSPF_SET_ROUTER_ID,
            driver=self.name
        )
    
    def _build_ospf_set_passive_interface(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        process_id = params.get("process_id")
        interface = params.get("interface")
        
        if not process_id or not interface:
            raise DriverBuildError("params require process_id, interface")
        
        path = f"{mount}/Cisco-IOS-XE-native:native/router"
        device_version = self._fetch_device_version(mount)
        
        if device_version.startswith("16."):
            payload = {
                "Cisco-IOS-XE-native:router": {
                    "Cisco-IOS-XE-ospf:ospf": [{
                        "id": int(process_id),
                        "passive-interface": {"interface": [interface]}
                    }]
                }
            }
        else:
            payload = {
                "Cisco-IOS-XE-native:router": {
                    "Cisco-IOS-XE-ospf:router-ospf": {
                        "ospf": {
                            "process-id": [{
                                "id": int(process_id),
                                "passive-interface": {"interface": [{"name": interface}]}
                            }]
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
            intent=Intents.ROUTING.OSPF_SET_PASSIVE_INTERFACE,
            driver=self.name
        )
    
    def _build_ospf_remove_passive_interface(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        process_id = params.get("process_id")
        interface = params.get("interface")
        
        if not process_id or not interface:
            raise DriverBuildError("params require process_id, interface")
        
        import urllib.parse
        encoded_interface = urllib.parse.quote(interface, safe='')
        device_version = self._fetch_device_version(mount)
        
        if device_version.startswith("16."):
            path = f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:ospf={process_id}/passive-interface/interface={encoded_interface}"
        else:
            path = f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:router-ospf/ospf/process-id={process_id}/passive-interface/interface={encoded_interface}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_REMOVE_PASSIVE_INTERFACE,
            driver=self.name
        )
    
    def _build_show_ospf_neighbors(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Show OSPF neighbors"""
        path = f"{mount}/Cisco-IOS-XE-ospf-oper:ospf-oper-data"

        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.OSPF_NEIGHBORS,
            driver=self.name
        )
    
    def _build_show_ospf_database(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Show OSPF LSDB"""
        path = f"{mount}/Cisco-IOS-XE-ospf-oper:ospf-oper-data"

        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.OSPF_DATABASE,
            driver=self.name
        )
    def _build_ospf_add_network_interface(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Add OSPF to interface (ip ospf {process_id} area {area_id})"""
        process_id = params.get("process_id")
        interface = params.get("interface")
        area = params.get("area")
        
        if process_id is None or interface is None or area is None:
            raise DriverBuildError("params require process_id, interface, area")
        
        iface_type, iface_num = self._parse_interface_name(interface)
        encoded_num = self._encode_interface_number(iface_num)
        
        path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"
        device_version = self._fetch_device_version(mount)
        
        # สำหรับ Interface OSPF คอนฟิก อาจจะต้องแยกระหว่าง 16 กับ 17 เช่นกัน
        if device_version.startswith("16."):
            payload = {
                f"Cisco-IOS-XE-native:{iface_type}": [{
                    "name": iface_num,
                    "ip": {
                        "Cisco-IOS-XE-ospf:router-ospf": { # สำหรับบาง revision ใน 16.x อาจจะใช้แบบนี้
                            "ospf": {
                                "process-id": [{
                                    "id": int(process_id),
                                    "area": [{"area-id": int(area)}]
                                }]
                            }
                        }
                    }
                }]
            }
        else:
            payload = {
                f"Cisco-IOS-XE-native:{iface_type}": [{
                    "name": iface_num,
                    "ip": {
                        "router-ospf": {
                            "ospf": {
                                "process-id": [{
                                    "id": int(process_id),
                                    "area": [{"area-id": int(area)}]
                                }]
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
            intent=Intents.ROUTING.OSPF_ADD_NETWORK_INTERFACE,
            driver=self.name
        )
    
    def _build_ospf_remove_network_interface(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Remove OSPF from interface"""
        process_id = params.get("process_id")
        interface = params.get("interface")
        
        if not all([process_id, interface]):
            raise DriverBuildError("params require process_id, interface")
        
        iface_type, iface_num = self._parse_interface_name(interface)
        encoded_num = self._encode_interface_number(iface_num)
        
        # ในการ Delete ระดับ Interface มักจะใช้ Path ลบข้อมูล ip ospf ทิ้งไปเลย
        path = (
            f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"
            f"/ip/Cisco-IOS-XE-ospf:router-ospf/ospf/process-id={process_id}"
        )

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"Accept": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_REMOVE_NETWORK_INTERFACE,
            driver=self.name
        )


# ===== Utility Functions =====
def _prefix_to_netmask(prefix: int) -> str:
    """Convert CIDR prefix to dotted decimal netmask"""
    if prefix < 0 or prefix > 32:
        return "0.0.0.0"
    mask = (0xffffffff << (32 - prefix)) & 0xffffffff
    return ".".join(str((mask >> (8*i)) & 0xff) for i in [3, 2, 1, 0])


def _wildcard_to_netmask(wildcard: str) -> str:
    """Convert wildcard mask to subnet mask (e.g. 0.0.0.255 -> 255.255.255.0)"""
    octets = wildcard.split(".")
    return ".".join(str(255 - int(o)) for o in octets)

