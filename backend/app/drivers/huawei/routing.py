"""
Huawei Routing Driver (VRP8)
OSPF and Static Routing operations using Huawei native YANG models

YANG Models:
- huawei-ospfv2 (Revision 2018-11-23)
- huawei-staticrt (for static routes)

Critical Notes:
- OSPF uses hidden intermediate container: ospfv2comm
- URL hierarchy: /huawei-ospfv2:ospfv2/ospfv2comm/ospfSites/ospfSite={processId}
"""
from typing import Any, Dict
import urllib.parse
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class HuaweiRoutingDriver(BaseDriver):
    """
    Huawei VRP8 Routing Driver
    
    Supports OSPF and static routing using huawei-ospfv2 and huawei-staticrt models.
    """
    name = "huawei"

    SUPPORTED_INTENTS = {
        # OSPF
        Intents.ROUTING.OSPF_ENABLE,
        Intents.ROUTING.OSPF_DISABLE,
        Intents.ROUTING.OSPF_ADD_NETWORK_INTERFACE,
        Intents.ROUTING.OSPF_REMOVE_NETWORK_INTERFACE,
        Intents.ROUTING.OSPF_SET_ROUTER_ID,
        Intents.SHOW.OSPF_NEIGHBORS,
        Intents.SHOW.OSPF_DATABASE,
        # Static Routes
        Intents.ROUTING.STATIC_ADD,
        Intents.ROUTING.STATIC_DELETE,
        Intents.SHOW.IP_ROUTE,
    }

    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        mount = odl_mount_base(device.node_id)

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
        
        if intent == Intents.SHOW.OSPF_NEIGHBORS:
            return self._build_show_ospf_neighbors(mount, params)
        
        if intent == Intents.SHOW.OSPF_DATABASE:
            return self._build_show_ospf_database(mount, params)
        
        # ===== STATIC ROUTING INTENTS =====
        if intent == Intents.ROUTING.STATIC_ADD:
            return self._build_static_add(mount, params)
        
        if intent == Intents.ROUTING.STATIC_DELETE:
            return self._build_static_delete(mount, params)
        
        if intent == Intents.SHOW.IP_ROUTE:
            return self._build_show_ip_route(mount, params)

        raise UnsupportedIntent(intent)

    # =========================================================================
    # OSPF Builder Methods (huawei-ospfv2)
    # =========================================================================
    
    def _build_ospf_enable(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Create OSPF process using VRP8 huawei-ospfv2 model.
        
        Path: /huawei-ospfv2:ospfv2/ospfv2comm/ospfSites/ospfSite={processId}
        
        Note: ospfv2comm is a hidden intermediate container in VRP8!
        """
        process_id = params.get("process_id", 1)
        router_id = params.get("router_id")
        description = params.get("description", f"OSPF_Process_{process_id}")
        
        path = f"{mount}/huawei-ospfv2:ospfv2/ospfv2comm/ospfSites/ospfSite={process_id}"
        
        payload = {
            "huawei-ospfv2:ospfSite": [{
                "processId": int(process_id),
                "description": description
            }]
        }
        
        # Add router ID if provided
        if router_id:
            payload["huawei-ospfv2:ospfSite"][0]["routerId"] = router_id

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_ENABLE,
            driver=self.name
        )
    
    def _build_ospf_disable(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Delete OSPF process"""
        process_id = params.get("process_id", 1)
        
        path = f"{mount}/huawei-ospfv2:ospfv2/ospfv2comm/ospfSites/ospfSite={process_id}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_DISABLE,
            driver=self.name
        )
    
    def _build_ospf_add_network_interface(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Add network command to OSPF area.
        
        Path: .../ospfSite={processId}/areas/area={areaId}
        
        Params:
            process_id: OSPF process ID (default: 1)
            area: Area ID in dotted format (e.g., "0.0.0.0")
            network: Network address (e.g., "192.168.1.0")
            wildcard: Wildcard mask (e.g., "0.0.0.255")
        """
        process_id = params.get("process_id", 1)
        area_id = params.get("area", "0.0.0.0")
        network = params.get("network")
        wildcard = params.get("wildcard")
        
        if not network or not wildcard:
            raise DriverBuildError("params require network, wildcard")
        
        # URL encode area ID (contains dots)
        encoded_area = urllib.parse.quote(str(area_id), safe='')
        
        path = f"{mount}/huawei-ospfv2:ospfv2/ospfv2comm/ospfSites/ospfSite={process_id}/areas/area={encoded_area}"
        
        payload = {
            "huawei-ospfv2:area": [{
                "areaId": str(area_id),
                "authenticationMode": "none",
                "networks": {
                    "network": [{
                        "ipAddress": network,
                        "wildcardMask": wildcard
                    }]
                }
            }]
        }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_ADD_NETWORK_INTERFACE,
            driver=self.name
        )
    
    def _build_ospf_remove_network_interface(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Remove network from OSPF area"""
        process_id = params.get("process_id", 1)
        area_id = params.get("area", "0.0.0.0")
        network = params.get("network")
        
        if not network:
            raise DriverBuildError("params require network")
        
        encoded_area = urllib.parse.quote(str(area_id), safe='')
        encoded_network = urllib.parse.quote(network, safe='')
        
        path = f"{mount}/huawei-ospfv2:ospfv2/ospfv2comm/ospfSites/ospfSite={process_id}/areas/area={encoded_area}/networks/network={encoded_network}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_REMOVE_NETWORK_INTERFACE,
            driver=self.name
        )
    
    def _build_ospf_set_router_id(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Set OSPF router ID"""
        process_id = params.get("process_id", 1)
        router_id = params.get("router_id")
        
        if not router_id:
            raise DriverBuildError("params require router_id")
        
        path = f"{mount}/huawei-ospfv2:ospfv2/ospfv2comm/ospfSites/ospfSite={process_id}"
        
        payload = {
            "huawei-ospfv2:ospfSite": [{
                "processId": int(process_id),
                "routerId": router_id
            }]
        }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_SET_ROUTER_ID,
            driver=self.name
        )
    
    def _build_show_ospf_neighbors(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Get OSPF neighbors.
        
        Note: Append ?content=config if 500 error occurs due to ODL codec bugs.
        """
        process_id = params.get("process_id", 1)
        
        # Use config content to avoid ODL codec issues with operational data
        path = f"{mount}/huawei-ospfv2:ospfv2/ospfv2comm/ospfSites/ospfSite={process_id}?content=config"

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
        """Get OSPF LSDB"""
        process_id = params.get("process_id", 1)
        
        path = f"{mount}/huawei-ospfv2:ospfv2/ospfv2comm/ospfSites/ospfSite={process_id}?content=config"

        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.OSPF_DATABASE,
            driver=self.name
        )

    # =========================================================================
    # Static Routing Builder Methods (huawei-routing)
    # =========================================================================
    
    def _build_static_add(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Add static route using huawei-routing module.
        
        VRP8 YANG Path: /huawei-routing:routing/static-routes/ipv4-static-route
        
        Params:
            prefix: Destination prefix (e.g., "10.0.0.0/24")
            next_hop: Next-hop IP address
            vrf_name: VRF name (default: "_public_" for global)
        """
        prefix = params.get("prefix")  # e.g., "10.0.0.0/24"
        next_hop = params.get("next_hop")
        vrf_name = params.get("vrf_name", "_public_")
        
        if not prefix or not next_hop:
            raise DriverBuildError("params require prefix, next_hop")
        
        # Parse prefix
        network, mask_len = prefix.split("/")
        
        path = f"{mount}/huawei-routing:routing/static-routes/ipv4-static-route"
        
        payload = {
            "huawei-routing:ipv4-static-route": [{
                "vrf-name": vrf_name,
                "destination-ip": network,
                "mask-length": int(mask_len),
                "nexthop-address": next_hop
            }]
        }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.ROUTING.STATIC_ADD,
            driver=self.name
        )
    
    def _build_static_delete(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Delete static route"""
        prefix = params.get("prefix")
        next_hop = params.get("next_hop")
        vrf_name = params.get("vrf_name", "_public_")
        
        if not prefix:
            raise DriverBuildError("params require prefix")
        
        network, mask_len = prefix.split("/")
        encoded_network = urllib.parse.quote(network, safe='')
        encoded_nexthop = urllib.parse.quote(next_hop, safe='') if next_hop else ""
        encoded_vrf = urllib.parse.quote(vrf_name, safe='')
        
        # Build path with key components
        path = f"{mount}/huawei-routing:routing/static-routes/ipv4-static-route={encoded_vrf},{encoded_network},{mask_len},{encoded_nexthop}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.ROUTING.STATIC_DELETE,
            driver=self.name
        )
    
    def _build_show_ip_route(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Get static routing table"""
        path = f"{mount}/huawei-routing:routing/static-routes?content=config"

        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.IP_ROUTE,
            driver=self.name
        )


# ===== Utility Functions =====
def _prefix_to_netmask(prefix: int) -> str:
    """Convert CIDR prefix to dotted decimal netmask"""
    if prefix < 0 or prefix > 32:
        return "0.0.0.0"
    mask = (0xffffffff << (32 - prefix)) & 0xffffffff
    return ".".join(str((mask >> (8*i)) & 0xff) for i in [3, 2, 1, 0])


def _netmask_to_wildcard(netmask: str) -> str:
    """Convert netmask to wildcard mask"""
    octets = netmask.split(".")
    return ".".join(str(255 - int(o)) for o in octets)
