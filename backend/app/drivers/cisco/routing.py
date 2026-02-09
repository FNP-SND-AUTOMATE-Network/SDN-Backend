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
        Intents.ROUTING.OSPF_REMOVE_NETWORK,
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
        
        if intent == Intents.ROUTING.OSPF_ADD_NETWORK:
            return self._build_ospf_add_network(mount, params)
        
        if intent == Intents.ROUTING.OSPF_REMOVE_NETWORK:
            return self._build_ospf_remove_network(mount, params)
        
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

        raise UnsupportedIntent(intent)

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
        # Use ietf-routing model - works even without static routes
        # Cisco-IOS-XE-native:native/ip/route returns 409 if no static routes configured
        path = f"{mount}/ietf-routing:routing"

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
        """Get IP interface brief (summary view)"""
        # Cisco interface summary
        path = f"{mount}/ietf-interfaces:interfaces-state"

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
    
    def _build_ospf_enable(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Enable OSPF process using Cisco IOS-XE native model"""
        process_id = params.get("process_id")
        router_id = params.get("router_id")
        
        if not process_id:
            raise DriverBuildError("params require process_id")
        
        path = f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:router-ospf/ospf/process-id={process_id}"
        
        ospf_config = {
            "Cisco-IOS-XE-ospf:process-id": {
                "id": int(process_id)
            }
        }
        
        if router_id:
            ospf_config["Cisco-IOS-XE-ospf:process-id"]["router-id"] = router_id

        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=ospf_config,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_ENABLE,
            driver=self.name
        )
    
    def _build_ospf_disable(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Disable/Remove OSPF process"""
        process_id = params.get("process_id")
        
        if not process_id:
            raise DriverBuildError("params require process_id")
        
        path = f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:router-ospf/ospf/process-id={process_id}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_DISABLE,
            driver=self.name
        )
    
    def _build_ospf_add_network(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Add network to OSPF area (Cisco style: network x.x.x.x wildcard area X)"""
        process_id = params.get("process_id")
        network = params.get("network")
        wildcard = params.get("wildcard")
        area = params.get("area")
        
        if not all([process_id, network, wildcard, area]):
            raise DriverBuildError("params require process_id, network, wildcard, area")
        
        # Cisco uses ip,wildcard as key
        path = (
            f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:router-ospf"
            f"/ospf/process-id={process_id}/network={network},{wildcard}"
        )
        
        payload = {
            "Cisco-IOS-XE-ospf:network": {
                "ip": network,
                "wildcard": wildcard,
                "area": int(area)
            }
        }

        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"Content-Type": "application/yang-data+json", "Accept": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_ADD_NETWORK,
            driver=self.name
        )
    
    def _build_ospf_remove_network(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Remove network from OSPF"""
        process_id = params.get("process_id")
        network = params.get("network")
        wildcard = params.get("wildcard")
        area = params.get("area")
        
        if not all([process_id, network, wildcard, area]):
            raise DriverBuildError("params require process_id, network, wildcard, area")
        
        path = (
            f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:router-ospf"
            f"/ospf/process-id={process_id}/network={network},{wildcard}"
        )

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_REMOVE_NETWORK,
            driver=self.name
        )
    
    def _build_ospf_set_router_id(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Set OSPF router ID"""
        process_id = params.get("process_id")
        router_id = params.get("router_id")
        
        if not process_id or not router_id:
            raise DriverBuildError("params require process_id, router_id")
        
        path = (
            f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:router-ospf"
            f"/ospf/process-id={process_id}/router-id"
        )
        
        payload = {
            "Cisco-IOS-XE-ospf:router-id": router_id
        }

        return RequestSpec(
            method="PUT",
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
        
        path = (
            f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:router-ospf"
            f"/ospf/process-id={process_id}"
        )
        
        payload = {
            "Cisco-IOS-XE-ospf:process-id": {
                "id": int(process_id),
                "passive-interface": {
                    "interface": [interface]
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
        
        path = (
            f"{mount}/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-ospf:router-ospf"
            f"/ospf/process-id={process_id}/passive-interface/interface={interface}"
        )

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_REMOVE_PASSIVE_INTERFACE,
            driver=self.name
        )
    
    def _build_show_ospf_neighbors(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Show OSPF neighbors"""
        process_id = params.get("process_id", "1")
        
        # Cisco IOS-XE OSPF operational data
        path = (
            f"{mount}/Cisco-IOS-XE-ospf-oper:ospf-oper-data"
            f"/ospf-state/ospf-instance={process_id}/ospf-area"
        )

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
        process_id = params.get("process_id", "1")
        
        path = (
            f"{mount}/Cisco-IOS-XE-ospf-oper:ospf-oper-data"
            f"/ospf-state/ospf-instance={process_id}/link-scope-lsas"
        )

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
