"""
Huawei DHCP Driver (VRP8)
DHCP Server Pool configuration using huawei-ip-pool YANG model

YANG Module: huawei-ip-pool
URL Template: /huawei-ip-pool:ip-pool/global-pools/global-pool={poolName}
"""
from typing import Any, Dict, List
import urllib.parse
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


class HuaweiDhcpDriver(BaseDriver):
    """
    Huawei VRP8 DHCP Driver
    
    DHCP Server Pool configuration using huawei-ip-pool YANG model.
    """
    name = "huawei"

    SUPPORTED_INTENTS = {
        Intents.DHCP.CREATE_POOL,
        Intents.DHCP.DELETE_POOL,
        Intents.DHCP.UPDATE_POOL,
        Intents.SHOW.DHCP_POOLS,
    }

    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        mount = odl_mount_base(device.node_id)

        if intent == Intents.DHCP.CREATE_POOL:
            return self._build_dhcp_create_pool(mount, params)
        
        if intent == Intents.DHCP.DELETE_POOL:
            return self._build_dhcp_delete_pool(mount, params)
        
        if intent == Intents.DHCP.UPDATE_POOL:
            return self._build_dhcp_update_pool(mount, params)
        
        if intent == Intents.SHOW.DHCP_POOLS:
            return self._build_show_dhcp_pools(mount)

        raise UnsupportedIntent(intent, os_type=device.os_type)

    def _build_dhcp_create_pool(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Create DHCP pool using huawei-ip-pool module.
        
        VRP8 YANG Path: /huawei-ip-pool:ip-pool/global-pools/global-pool={poolName}
        
        Params:
            pool_name: Pool name (string)
            gateway: Gateway IP address
            mask: Subnet mask (e.g., "255.255.255.0")
            start_ip: Start of IP range
            end_ip: End of IP range
            dns_servers: List of DNS server IPs (optional)
            lease_days: Lease time in days (optional, default: 1)
        """
        pool_name = params.get("pool_name")
        gateway = params.get("gateway")
        mask = params.get("mask")
        start_ip = params.get("start_ip")
        end_ip = params.get("end_ip")
        dns_servers = params.get("dns_servers", [])
        lease_days = params.get("lease_days", 1)
        
        if not pool_name or not gateway or not mask:
            raise DriverBuildError("params require pool_name, gateway, mask")
        
        if not start_ip or not end_ip:
            raise DriverBuildError("params require start_ip, end_ip")
        
        encoded_pool = urllib.parse.quote(pool_name, safe='')
        path = f"{mount}/huawei-ip-pool:ip-pool/global-pools/global-pool={encoded_pool}"
        
        # Build pool configuration
        pool_config = {
            "pool-name": pool_name,
            "gateway": {
                "ip-address": gateway,
                "mask": mask
            },
            "section": [{
                "section-id": 0,
                "start-ip-address": start_ip,
                "end-ip-address": end_ip
            }]
        }
        
        # Add DNS servers if provided
        if dns_servers:
            if isinstance(dns_servers, str):
                dns_servers = [dns_servers]
            pool_config["dns-list"] = {
                "dns": [{"ip-address": ip} for ip in dns_servers]
            }
        
        # Add lease time
        if lease_days:
            pool_config["lease"] = {
                "day": int(lease_days),
                "hour": 0,
                "minute": 0
            }
        
        payload = {
            "huawei-ip-pool:global-pool": [pool_config]
        }

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.DHCP.CREATE_POOL,
            driver=self.name
        )
    
    def _build_dhcp_delete_pool(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Delete DHCP pool"""
        pool_name = params.get("pool_name")
        
        if not pool_name:
            raise DriverBuildError("params require pool_name")
        
        encoded_pool = urllib.parse.quote(pool_name, safe='')
        path = f"{mount}/huawei-ip-pool:ip-pool/global-pools/global-pool={encoded_pool}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.DHCP.DELETE_POOL,
            driver=self.name
        )
    
    def _build_dhcp_update_pool(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Update DHCP pool (same as create with PATCH)"""
        return self._build_dhcp_create_pool(mount, params)
    
    def _build_show_dhcp_pools(self, mount: str) -> RequestSpec:
        """Get all DHCP pools"""
        path = f"{mount}/huawei-ip-pool:ip-pool/global-pools?content=config"

        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.DHCP_POOLS,
            driver=self.name
        )
