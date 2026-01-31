"""
OpenConfig Routing Driver
รองรับ Routing operations เช่น static route, default route
"""
from typing import Any, Dict
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class OpenConfigRoutingDriver(BaseDriver):
    name = "openconfig"

    SUPPORTED_INTENTS = {
        Intents.ROUTING.STATIC_ADD,
        Intents.ROUTING.STATIC_DELETE,
        Intents.ROUTING.DEFAULT_ADD,
        Intents.ROUTING.DEFAULT_DELETE,
        Intents.SHOW.IP_ROUTE,
        # OSPF
        Intents.ROUTING.OSPF_ENABLE,
        Intents.ROUTING.OSPF_DISABLE,
        Intents.ROUTING.OSPF_ADD_NETWORK,
        Intents.ROUTING.OSPF_REMOVE_NETWORK,
        Intents.ROUTING.OSPF_SET_ROUTER_ID,
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
        
        if intent == Intents.SHOW.OSPF_NEIGHBORS:
            return self._build_show_ospf_neighbors(mount, params)
        
        if intent == Intents.SHOW.OSPF_DATABASE:
            return self._build_show_ospf_database(mount, params)

        raise UnsupportedIntent(intent)

    # ===== Builder Methods =====
    
    def _build_static_add(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Add static route using OpenConfig model"""
        prefix = params.get("prefix")
        next_hop = params.get("next_hop")
        
        if not prefix or not next_hop:
            raise DriverBuildError("params require prefix, next_hop")
        
        # แยก prefix และ mask
        if "/" in prefix:
            network, prefix_len = prefix.split("/")
        else:
            network = prefix
            prefix_len = params.get("mask", "24")
        
        metric = params.get("metric", 1)
        
        # OpenConfig static routes path
        path = (
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=STATIC,static"
            f"/static-routes/static={network}%2F{prefix_len}"
        )
        
        payload = {
            "openconfig-network-instance:static": {
                "prefix": f"{network}/{prefix_len}",
                "config": {
                    "prefix": f"{network}/{prefix_len}"
                },
                "next-hops": {
                    "next-hop": [{
                        "index": "0",
                        "config": {
                            "index": "0",
                            "next-hop": next_hop,
                            "metric": int(metric)
                        }
                    }]
                }
            }
        }

        return RequestSpec(
            method="PUT",
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
        
        if not prefix:
            raise DriverBuildError("params require prefix")
        
        if "/" in prefix:
            network, prefix_len = prefix.split("/")
        else:
            network = prefix
            prefix_len = params.get("mask", "24")
        
        path = (
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=STATIC,static"
            f"/static-routes/static={network}%2F{prefix_len}"
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
        
        metric = params.get("metric", 1)
        
        path = (
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=STATIC,static"
            f"/static-routes/static=0.0.0.0%2F0"
        )
        
        payload = {
            "openconfig-network-instance:static": {
                "prefix": "0.0.0.0/0",
                "config": {
                    "prefix": "0.0.0.0/0"
                },
                "next-hops": {
                    "next-hop": [{
                        "index": "0",
                        "config": {
                            "index": "0",
                            "next-hop": next_hop,
                            "metric": int(metric)
                        }
                    }]
                }
            }
        }

        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.ROUTING.DEFAULT_ADD,
            driver=self.name
        )
    
    def _build_default_delete(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Delete default route"""
        path = (
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=STATIC,static"
            f"/static-routes/static=0.0.0.0%2F0"
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
        """Get routing table"""
        vrf = params.get("vrf", "default")
        
        path = (
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance={vrf}/afts"
        )

        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.IP_ROUTE,
            driver=self.name
        )

    # ===== OSPF Methods =====
    
    def _build_ospf_enable(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Enable OSPF process using OpenConfig model"""
        process_id = params.get("process_id")
        router_id = params.get("router_id")
        
        if not process_id:
            raise DriverBuildError("params require process_id")
        
        path = (
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=OSPF,{process_id}"
        )
        
        config = {
            "identifier": "openconfig-policy-types:OSPF",
            "name": str(process_id)
        }
        
        ospf_config = {
            "openconfig-ospfv2:global": {
                "config": {}
            }
        }
        
        if router_id:
            ospf_config["openconfig-ospfv2:global"]["config"]["router-id"] = router_id
        
        payload = {
            "openconfig-network-instance:protocol": {
                "identifier": "openconfig-policy-types:OSPF",
                "name": str(process_id),
                "config": config,
                "ospfv2": ospf_config
            }
        }

        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.ROUTING.OSPF_ENABLE,
            driver=self.name
        )
    
    def _build_ospf_disable(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Disable/Remove OSPF process"""
        process_id = params.get("process_id")
        
        if not process_id:
            raise DriverBuildError("params require process_id")
        
        path = (
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=OSPF,{process_id}"
        )

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
        """Add network to OSPF area"""
        process_id = params.get("process_id")
        network = params.get("network")
        wildcard = params.get("wildcard")
        area = params.get("area")
        
        if not all([process_id, network, wildcard, area]):
            raise DriverBuildError("params require process_id, network, wildcard, area")
        
        # Convert wildcard to prefix length for OpenConfig
        prefix_len = _wildcard_to_prefix(wildcard)
        network_prefix = f"{network}/{prefix_len}"
        
        # URL encode the prefix
        encoded_prefix = network_prefix.replace("/", "%2F")
        
        path = (
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=OSPF,{process_id}"
            f"/ospfv2/areas/area={area}/interfaces/interface={encoded_prefix}"
        )
        
        payload = {
            "openconfig-ospfv2:interface": {
                "id": network_prefix,
                "config": {
                    "id": network_prefix
                }
            }
        }

        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
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
        
        prefix_len = _wildcard_to_prefix(wildcard)
        network_prefix = f"{network}/{prefix_len}"
        encoded_prefix = network_prefix.replace("/", "%2F")
        
        path = (
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=OSPF,{process_id}"
            f"/ospfv2/areas/area={area}/interfaces/interface={encoded_prefix}"
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
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=OSPF,{process_id}"
            f"/ospfv2/global/config"
        )
        
        payload = {
            "openconfig-ospfv2:config": {
                "router-id": router_id
            }
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
        """Show OSPF neighbors"""
        process_id = params.get("process_id", "1")
        
        path = (
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=OSPF,{process_id}"
            f"/ospfv2/areas"
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
            f"{mount}/openconfig-network-instance:network-instances"
            f"/network-instance=default/protocols/protocol=OSPF,{process_id}"
            f"/ospfv2/areas"
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
def _wildcard_to_prefix(wildcard: str) -> int:
    """Convert wildcard mask to CIDR prefix length"""
    try:
        parts = wildcard.split(".")
        # Invert wildcard to get netmask
        netmask_parts = [255 - int(p) for p in parts]
        binary = "".join(format(p, "08b") for p in netmask_parts)
        return binary.count("1")
    except:
        return 24