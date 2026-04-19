"""
Cisco IOS-XE DHCP Driver
DHCP Server Pool + Excluded Address configuration via Cisco-IOS-XE-dhcp YANG model

YANG Module: Cisco-IOS-XE-dhcp (augments Cisco-IOS-XE-native:native/ip/dhcp)
URL Template: .../Cisco-IOS-XE-native:native/ip/dhcp

Logic:
  - ถ้ามี excluded_addresses → payload จะมีทั้ง Cisco-IOS-XE-dhcp:excluded-address + pool
  - ถ้าไม่มี excluded_addresses → payload จะมีแค่ Cisco-IOS-XE-dhcp:pool
"""
from typing import Any, Dict, List
import urllib.parse
import ipaddress
from app.drivers.base import BaseDriver
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec
from app.builders.odl_paths import odl_mount_base
from app.core.errors import UnsupportedIntent, DriverBuildError
from app.core.intent_registry import Intents


def _prefix_to_netmask(prefix: int) -> str:
    if prefix < 0 or prefix > 32:
        raise DriverBuildError("mask prefix must be in range 0..32")
    mask = (0xffffffff << (32 - prefix)) & 0xffffffff if prefix > 0 else 0
    return ".".join(str((mask >> (8 * i)) & 0xff) for i in [3, 2, 1, 0])


def _normalize_ipv4_mask(mask_value: Any) -> str:
    text = str(mask_value or "").strip()
    if not text:
        raise DriverBuildError("mask is required")

    prefix_candidate = text[1:] if text.startswith("/") else text
    if prefix_candidate.isdigit():
        return _prefix_to_netmask(int(prefix_candidate))

    try:
        # Validate dotted mask and normalize to canonical dotted-decimal netmask.
        return str(ipaddress.IPv4Network(f"0.0.0.0/{text}", strict=False).netmask)
    except Exception as exc:
        raise DriverBuildError("mask must be dotted mask (255.255.255.0) or prefix (/24)") from exc


class CiscoDhcpDriver(BaseDriver):
    """
    Cisco IOS-XE DHCP Driver

    Supports:
      - dhcp.create_pool   (PATCH)  — สร้าง pool + optional excluded-address
      - dhcp.delete_pool   (DELETE) — ลบเฉพาะ pool ที่ระบุ
      - dhcp.delete_all    (DELETE) — ลบ DHCP ทั้งหมด
      - dhcp.update_pool   (PATCH)  — อัปเดต pool (idempotent, same as create)
      - show.dhcp_pools    (GET)    — ดึง DHCP config
    """
    name = "cisco"

    SUPPORTED_INTENTS = {
        Intents.DHCP.CREATE_POOL,
        Intents.DHCP.DELETE_POOL,
        Intents.DHCP.DELETE_ALL,
        Intents.DHCP.UPDATE_POOL,
        Intents.DHCP.ADD_EXCLUDED_ADDRESS,
        Intents.DHCP.DELETE_EXCLUDED_ADDRESS,
        Intents.SHOW.DHCP_POOLS,
    }

    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        mount = odl_mount_base(device.node_id)

        if intent == Intents.DHCP.CREATE_POOL:
            return self._build_dhcp_create_pool(mount, params, is_update=False)

        if intent == Intents.DHCP.DELETE_POOL:
            return self._build_dhcp_delete_pool(mount, params)

        if intent == Intents.DHCP.DELETE_ALL:
            return self._build_dhcp_delete_all(mount)

        if intent == Intents.DHCP.UPDATE_POOL:
            return self._build_dhcp_create_pool(mount, params, is_update=True)

        if intent == Intents.DHCP.ADD_EXCLUDED_ADDRESS:
            return self._build_dhcp_add_excluded_address(mount, params)
            
        if intent == Intents.DHCP.DELETE_EXCLUDED_ADDRESS:
            return self._build_dhcp_delete_excluded_address(mount, params)

        if intent == Intents.SHOW.DHCP_POOLS:
            return self._build_show_dhcp_pools(mount)

        raise UnsupportedIntent(intent, os_type=device.os_type)

    # ─── CREATE / UPDATE POOL ────────────────────────────────────────
    def _build_dhcp_create_pool(self, mount: str, params: Dict[str, Any], is_update: bool = False) -> RequestSpec:
        """
        Create or Update DHCP pool via PATCH on .../ip/dhcp

        Params:
            pool_name       (required): Pool ID เช่น "HinKong_BayView_ZoneA"
            network         (required): Subnet number เช่น "192.168.10.0"
            mask            (required): Subnet mask เช่น "255.255.255.0"
            default_router  (required): Gateway IP เช่น "192.168.10.1"
            dns_servers     (optional): List[str] เช่น ["8.8.8.8", "1.1.1.1"]
            excluded_addresses (optional): List[dict] เช่น [{"low": "x.x.x.x", "high": "y.y.y.y"}]
        """
        pool_name = params.get("pool_name")
        network = params.get("network")
        mask = params.get("mask")
        default_router = params.get("default_router") or params.get("gateway")
        dns_servers = params.get("dns_servers", [])
        excluded_addresses = params.get("excluded_addresses", [])

        if mask is not None and str(mask).strip() != "":
            mask = _normalize_ipv4_mask(mask)
        
        # Support Unified Interface (Huawei-style)
        start_ip = params.get("start_ip")
        end_ip = params.get("end_ip")
        
        if not network and default_router and mask:
            try:
                # Calculate network from gateway and mask
                net = ipaddress.IPv4Network(f"{default_router}/{mask}", strict=False)
                network = str(net.network_address)
                
                # Auto-calculate excluded address range if start_ip and end_ip are provided
                if start_ip and end_ip and not excluded_addresses:
                    start_ip_obj = ipaddress.IPv4Address(start_ip)
                    end_ip_obj = ipaddress.IPv4Address(end_ip)
                    
                    usable_first = net.network_address + 1
                    usable_last = net.broadcast_address - 1
                    
                    if start_ip_obj > usable_first:
                        excluded_addresses.append({
                            "low": str(usable_first),
                            "high": str(start_ip_obj - 1)
                        })
                    
                    if end_ip_obj < usable_last:
                        excluded_addresses.append({
                            "low": str(end_ip_obj + 1),
                            "high": str(usable_last)
                        })
            except Exception:
                pass

        if not pool_name:
            raise DriverBuildError("params require pool_name")

        if not is_update:
            if not network or not mask or not default_router:
                raise DriverBuildError(
                    "params require pool_name, network, mask, default_router (or unified gateway/start_ip/end_ip)"
                )

        # ── Build pool entry ──
        pool_entry: Dict[str, Any] = {
            "id": pool_name,
        }
        
        if network and mask:
            pool_entry["network"] = {
                "primary-network": {
                    "number": network,
                    "mask": mask,
                }
            }
        elif (network and not mask) or (mask and not network):
            raise DriverBuildError("Both network and mask must be provided together")

        if default_router:
            pool_entry["default-router"] = {
                "default-router-list": [default_router]
            }

        # DNS servers (optional)
        if dns_servers:
            if isinstance(dns_servers, str):
                dns_servers = [dns_servers]
            pool_entry["dns-server"] = {
                "dns-server-list": dns_servers
            }

        # ── Build DHCP payload ──
        dhcp_body: Dict[str, Any] = {
            "Cisco-IOS-XE-dhcp:pool": [pool_entry]
        }

        # Conditionally add excluded-address
        if excluded_addresses:
            low_high_list = []
            for exc in excluded_addresses:
                low = exc.get("low") or exc.get("low_address") or exc.get("low-address")
                high = exc.get("high") or exc.get("high_address") or exc.get("high-address")
                if low and high:
                    low_high_list.append({
                        "low-address": low,
                        "high-address": high,
                    })
            if low_high_list:
                dhcp_body["Cisco-IOS-XE-dhcp:excluded-address"] = {
                    "low-high-address-list": low_high_list
                }

        payload = {
            "Cisco-IOS-XE-native:dhcp": dhcp_body
        }

        path = f"{mount}/Cisco-IOS-XE-native:native/ip/dhcp"

        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.DHCP.CREATE_POOL,
            driver=self.name,
        )

    # ─── DELETE SPECIFIC POOL ────────────────────────────────────────
    def _build_dhcp_delete_pool(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Delete specific DHCP pool by pool_name"""
        pool_name = params.get("pool_name")
        if not pool_name:
            raise DriverBuildError("params require pool_name")

        encoded_pool = urllib.parse.quote(pool_name, safe='')
        path = f"{mount}/Cisco-IOS-XE-native:native/ip/dhcp/Cisco-IOS-XE-dhcp:pool={encoded_pool}"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.DHCP.DELETE_POOL,
            driver=self.name,
        )

    # ─── ADD EXCLUDED ADDRESS ─────────────────────────────────────────
    def _build_dhcp_add_excluded_address(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Add a global excluded address range"""
        low = params.get("low_address")
        high = params.get("high_address")
        
        if not low or not high:
             raise DriverBuildError("params require low_address, high_address")

        payload = {
            "Cisco-IOS-XE-native:dhcp": {
                "Cisco-IOS-XE-dhcp:excluded-address": {
                    "low-high-address-list": [
                        {
                            "low-address": low,
                            "high-address": high
                        }
                    ]
                }
            }
        }
        
        path = f"{mount}/Cisco-IOS-XE-native:native/ip/dhcp"
        
        return RequestSpec(
            method="PATCH",
            datastore="config",
            path=path,
            payload=payload,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.DHCP.ADD_EXCLUDED_ADDRESS,
            driver=self.name,
        )

    # ─── DELETE EXCLUDED ADDRESS ──────────────────────────────────────
    def _build_dhcp_delete_excluded_address(self, mount: str, params: Dict[str, Any]) -> RequestSpec:
        """Delete a global excluded address range"""
        low = params.get("low_address")
        high = params.get("high_address")
        
        if not low or not high:
             raise DriverBuildError("params require low_address, high_address")

        # Need fully qualified path with keys string
        path = f"{mount}/Cisco-IOS-XE-native:native/ip/dhcp/Cisco-IOS-XE-dhcp:excluded-address/low-high-address-list={low},{high}"
        
        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.DHCP.DELETE_EXCLUDED_ADDRESS,
            driver=self.name,
        )

    # ─── DELETE ALL DHCP ─────────────────────────────────────────────
    def _build_dhcp_delete_all(self, mount: str) -> RequestSpec:
        """Delete all DHCP configuration (pool + excluded-address)"""
        path = f"{mount}/Cisco-IOS-XE-native:native/ip/dhcp"

        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={"content-type": "application/yang-data+json"},
            intent=Intents.DHCP.DELETE_ALL,
            driver=self.name,
        )

    # ─── SHOW DHCP POOLS ────────────────────────────────────────────
    def _build_show_dhcp_pools(self, mount: str) -> RequestSpec:
        """Get all DHCP pools from device"""
        path = f"{mount}/Cisco-IOS-XE-native:native/ip/dhcp"

        return RequestSpec(
            method="GET",
            datastore="config",
            path=path,
            payload=None,
            headers={"accept": "application/yang-data+json"},
            intent=Intents.SHOW.DHCP_POOLS,
            driver=self.name,
        )
