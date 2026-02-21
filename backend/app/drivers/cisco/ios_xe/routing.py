"""
Cisco Routing Driver
รองรับ Routing operations สำหรับ Cisco IOS-XE devices
"""
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
        Intents.ROUTING.OSPF_ADD_NETWORK_INTERFACE,
        Intents.ROUTING.OSPF_REMOVE_NETWORK_INTERFACE,
        Intents.ROUTING.OSPF_SET_ROUTER_ID,
        Intents.ROUTING.OSPF_SET_PASSIVE_INTERFACE,
        Intents.ROUTING.OSPF_REMOVE_PASSIVE_INTERFACE,
        Intents.SHOW.OSPF_NEIGHBORS,
        Intents.SHOW.OSPF_DATABASE,
    }

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
    # Path: /Cisco-IOS-XE-native:native/router
    # Payload: { "Cisco-IOS-XE-native:router": { "ospf": [...] } }
    
    def _build_ospf_enable(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Enable OSPF process using Cisco-IOS-XE-ospf:router-ospf"""
        process_id = params.get("process_id")
        router_id = params.get("router_id")
        
        if not process_id:
            raise DriverBuildError("params require process_id")
        
        path = f"{mount}/Cisco-IOS-XE-native:native/router"
        
        ospf_entry = {"id": int(process_id)}
        if router_id:
            ospf_entry["router-id"] = router_id

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
        """Disable/Remove OSPF process"""
        process_id = params.get("process_id")
        
        if not process_id:
            raise DriverBuildError("params require process_id")
        
        # DELETE specific OSPF process
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
    
    def _build_ospf_add_network_interface(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Add OSPF to interface (ip ospf {process_id} area {area_id})
        
        Uses interface-level OSPF config instead of router-level network command.
        Path: .../Cisco-IOS-XE-native:native/interface/{Type}={Number}
        Payload: ip.router-ospf.ospf.process-id[].id + area[].area-id
        """
        process_id = params.get("process_id")
        interface = params.get("interface")
        area = params.get("area")
        
        if process_id is None or interface is None or area is None:
            raise DriverBuildError("params require process_id, interface, area")
        
        iface_type, iface_num = self._parse_interface_name(interface)
        encoded_num = self._encode_interface_number(iface_num)
        
        path = f"{mount}/Cisco-IOS-XE-native:native/interface/{iface_type}={encoded_num}"
        
        payload = {
            f"Cisco-IOS-XE-native:{iface_type}": [{
                "name": iface_num,
                "ip": {
                    "router-ospf": {
                        "ospf": {
                            "process-id": [{
                                "id": int(process_id),
                                "area": [{
                                    "area-id": int(area)
                                }]
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
        """
        Remove OSPF from interface (no ip ospf {process_id} area {area_id})
        
        DELETE the router-ospf config from the interface.
        """
        process_id = params.get("process_id")
        interface = params.get("interface")
        
        if not all([process_id, interface]):
            raise DriverBuildError("params require process_id, interface")
        
        iface_type, iface_num = self._parse_interface_name(interface)
        encoded_num = self._encode_interface_number(iface_num)
        
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
    
    def _build_ospf_set_router_id(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Set OSPF router ID"""
        process_id = params.get("process_id")
        router_id = params.get("router_id")
        
        if not process_id or not router_id:
            raise DriverBuildError("params require process_id, router_id")
        
        path = f"{mount}/Cisco-IOS-XE-native:native/router"
        
        payload = {
            "Cisco-IOS-XE-native:router": {
                "Cisco-IOS-XE-ospf:router-ospf": {
                    "ospf": {
                        "process-id": [{
                            "id": int(process_id),
                            "router-id": router_id
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
            intent=Intents.ROUTING.OSPF_SET_ROUTER_ID,
            driver=self.name
        )
    
    def _build_ospf_set_passive_interface(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Set interface as OSPF passive"""
        process_id = params.get("process_id")
        interface = params.get("interface")
        
        if not process_id or not interface:
            raise DriverBuildError("params require process_id, interface")
        
        path = f"{mount}/Cisco-IOS-XE-native:native/router"
        
        payload = {
            "Cisco-IOS-XE-native:router": {
                "Cisco-IOS-XE-ospf:router-ospf": {
                    "ospf": {
                        "process-id": [{
                            "id": int(process_id),
                            "passive-interface": {
                                "interface": [interface]
                            }
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
        """Remove passive interface setting"""
        process_id = params.get("process_id")
        interface = params.get("interface")
        
        if not process_id or not interface:
            raise DriverBuildError("params require process_id, interface")
        
        path = f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:router-ospf/ospf/process-id={process_id}/passive-interface/interface={interface}"

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
