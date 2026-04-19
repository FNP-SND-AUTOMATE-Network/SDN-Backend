import httpx
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import ipaddress


class PhpipamService:
    def __init__(self):
        self.base_url = os.getenv("PHPIPAM_BASE_URL", "https://localhost:443")
        self.app_id = os.getenv("PHPIPAM_APP_ID")
        self.username = os.getenv("PHPIPAM_USERNAME")
        self.password = os.getenv("PHPIPAM_PASSWORD")
        self.enabled = os.getenv("PHPIPAM_ENABLED", "true").lower() == "true"
        
        # Token management
        self.token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        
        # Validate configuration
        if self.enabled and not all([self.app_id, self.username, self.password]):
            print("WARNING: phpIPAM is enabled but credentials are missing")
            self.enabled = False
    
    @property
    def api_url(self) -> str:
        return f"{self.base_url}/api/{self.app_id}"
    
    def is_token_valid(self) -> bool:
        if not self.token or not self.token_expires:
            return False
        return datetime.now() < self.token_expires
    
    async def authenticate(self) -> bool:
        if not self.enabled:
            return False
        
        # ถ้า token ยังใช้ได้อยู่ ไม่ต้อง authenticate ใหม่
        if self.is_token_valid():
            return True
        
        try:
            # Disable SSL verification for self-signed certificates
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.post(
                    f"{self.api_url}/user/",
                    auth=(self.username, self.password),
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.token = data.get("data", {}).get("token")
                    
                    # Token หมดอายุใน 6 ชั่วโมง (default)
                    self.token_expires = datetime.now() + timedelta(hours=6)
                    
                    print(f"[phpIPAM] Authentication successful, token expires at {self.token_expires}")
                    return True
                else:
                    print(f"[phpIPAM] Authentication failed: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            print(f"[phpIPAM] Authentication error: {e}")
            return False
    
    async def _request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        
        # Ensure authenticated
        if not await self.authenticate():
            return None
        
        try:
            headers = {"token": self.token}
            url = f"{self.api_url}/{endpoint}"
            
            # Disable SSL verification for self-signed certificates
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    params=params,
                    timeout=10.0
                )
                
                if response.status_code in [200, 201]:
                    return response.json()
                elif response.status_code == 404:
                    # phpIPAM returns 404 for empty results (e.g. empty subnet, IP not found)
                    # This is normal — not an error. Return parsed body so callers can check.
                    return response.json()
                else:
                    print(f"[phpIPAM] Request failed: {method} {endpoint} - {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            print(f"[phpIPAM] Request error: {e}")
            return None
    
    # ========= Subnet Management =========
    
    async def get_subnets(self) -> List[Dict[str, Any]]:
        result = await self._request("GET", "subnets/")
        if result and result.get("success"):
            return result.get("data", [])
        return []
    
    async def get_subnet(self, subnet_id: str) -> Optional[Dict[str, Any]]:
        result = await self._request("GET", f"subnets/{subnet_id}/")
        if result and result.get("success"):
            return result.get("data")
        return None
    
    async def get_subnet_addresses(self, subnet_id: str) -> List[Dict[str, Any]]:
        result = await self._request("GET", f"subnets/{subnet_id}/addresses/")
        if result and result.get("success"):
            return result.get("data", [])
        return []
    
    async def create_subnet(
        self,
        subnet: str,
        mask: str,
        section_id: str,
        description: str = None,
        vlan_id: str = None,
        master_subnet_id: str = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        data = {
            "subnet": subnet,
            "mask": mask,
            "sectionId": section_id,
        }
        
        if description:
            data["description"] = description
        if vlan_id:
            data["vlanId"] = vlan_id
        if master_subnet_id:
            data["masterSubnetId"] = master_subnet_id
        
        # Add any additional fields
        data.update(kwargs)
        
        result = await self._request("POST", "subnets/", data=data)
        if result and result.get("success"):
            # Get the created subnet ID and fetch full details
            subnet_id = result.get("id")
            if subnet_id:
                return await self.get_subnet(subnet_id)
        return None
    
    async def update_subnet(
        self,
        subnet_id: str,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        if not kwargs:
            return None
        
        result = await self._request("PATCH", f"subnets/{subnet_id}/", data=kwargs)
        if result and result.get("success"):
            return await self.get_subnet(subnet_id)
        return None
    
    async def delete_subnet(self, subnet_id: str) -> bool:
        result = await self._request("DELETE", f"subnets/{subnet_id}/")
        return result is not None and result.get("success", False)
    
    async def get_subnet_usage(self, subnet_id: str) -> Optional[Dict[str, Any]]:
        result = await self._request("GET", f"subnets/{subnet_id}/usage/")
        if result and result.get("success"):
            return result.get("data")
        return None
    
    # ========= Sections Management =========
    
    async def get_sections(self) -> List[Dict[str, Any]]:
        result = await self._request("GET", "sections/")
        if result and result.get("success"):
            return result.get("data", [])
        return []
    
    async def get_section(self, section_id: str) -> Optional[Dict[str, Any]]:
        result = await self._request("GET", f"sections/{section_id}/")
        if result and result.get("success"):
            return result.get("data")
        return None
    
    async def create_section(
        self,
        name: str,
        description: str = None,
        master_section: str = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        data = {"name": name}
        
        if description:
            data["description"] = description
        if master_section:
            data["masterSection"] = master_section
        
        # Add any additional fields
        data.update(kwargs)
        
        result = await self._request("POST", "sections/", data=data)
        if result and result.get("success"):
            # Get the created section ID and fetch full details
            section_id = result.get("id")
            if section_id:
                return await self.get_section(section_id)
        return None
    
    async def update_section(
        self,
        section_id: str,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        if not kwargs:
            return None
        
        result = await self._request("PATCH", f"sections/{section_id}/", data=kwargs)
        if result and result.get("success"):
            return await self.get_section(section_id)
        return None
    
    async def delete_section(self, section_id: str) -> bool:
        result = await self._request("DELETE", f"sections/{section_id}/")
        return result is not None and result.get("success", False)
    
    async def get_section_subnets(self, section_id: str) -> List[Dict[str, Any]]:
        result = await self._request("GET", f"sections/{section_id}/subnets/")
        if result and result.get("success"):
            return result.get("data", [])
        return []
    
    # ========= MAC Address Validation =========
    
    @staticmethod
    def _is_valid_mac(mac: str) -> bool:
        """Check if MAC address is valid for phpIPAM (XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX)"""
        if not mac:
            return False
        import re
        # Accept formats: 00:11:22:33:44:55, 00-11-22-33-44-55, 001122334455, 0011.2233.4455
        mac_clean = re.sub(r'[.:\-]', '', mac)
        return bool(re.match(r'^[0-9a-fA-F]{12}$', mac_clean))
    
    @staticmethod
    def _normalize_mac(mac: str) -> Optional[str]:
        """Normalize MAC to XX:XX:XX:XX:XX:XX format for phpIPAM"""
        if not mac:
            return None
        import re
        mac_clean = re.sub(r'[.:\-]', '', mac)
        if not re.match(r'^[0-9a-fA-F]{12}$', mac_clean):
            return None  # Invalid MAC — skip
        # Format as AA:BB:CC:DD:EE:FF
        return ':'.join(mac_clean[i:i+2] for i in range(0, 12, 2)).lower()

    # ========= IP Address Management =========
    
    async def create_ip_address(
        self,
        subnet_id: str,
        ip_address: str,
        hostname: Optional[str] = None,
        description: Optional[str] = None,
        mac_address: Optional[str] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        data = {
            "subnetId": subnet_id,
            "ip": ip_address,
        }
        
        if hostname:
            data["hostname"] = hostname
        if description:
            data["description"] = description
        
        # Validate & normalize MAC before sending to phpIPAM
        if mac_address:
            normalized_mac = self._normalize_mac(mac_address)
            if normalized_mac:
                data["mac"] = normalized_mac
            else:
                print(f"[phpIPAM] Skipping invalid MAC '{mac_address}' — not sending to phpIPAM")
        
        # Add any additional fields
        data.update(kwargs)
        
        result = await self._request("POST", "addresses/", data=data)
        if result and result.get("success"):
            # Get the created address ID
            address_id = result.get("id")
            if address_id:
                return await self.get_ip_address(address_id)
        return None
    
    async def get_ip_address(self, address_id: str) -> Optional[Dict[str, Any]]:
        result = await self._request("GET", f"addresses/{address_id}/")
        if result and result.get("success"):
            return result.get("data")
        return None
    
    async def update_ip_address(
        self,
        address_id: str,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        if not kwargs:
            return None
        
        result = await self._request("PATCH", f"addresses/{address_id}/", data=kwargs)
        if result and result.get("success"):
            return await self.get_ip_address(address_id)
        return None
    
    async def delete_ip_address(self, address_id: str) -> bool:
        result = await self._request("DELETE", f"addresses/{address_id}/")
        return result is not None and result.get("success", False)
    
    async def search_ip(self, ip_address: str) -> Optional[Dict[str, Any]]:
        result = await self._request("GET", f"addresses/search/{ip_address}/")
        if result and result.get("success"):
            data = result.get("data", [])
            return data[0] if data else None
        return None
    
    async def get_first_free_ip(self, subnet_id: str) -> Optional[str]:
        result = await self._request("GET", f"subnets/{subnet_id}/first_free/")
        if result and result.get("success"):
            return result.get("data")
        return None
    
    # ========= Helper Methods =========
    
    async def assign_ip_to_device(
        self,
        device_name: str,
        subnet_id: str,
        mac_address: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        # หา IP ว่างแรก
        free_ip = await self.get_first_free_ip(subnet_id)
        if not free_ip:
            print(f"[phpIPAM] No free IP in subnet {subnet_id}")
            return None
        
        # สร้าง IP address
        return await self.create_ip_address(
            subnet_id=subnet_id,
            ip_address=free_ip,
            hostname=device_name,
            description=description,
            mac_address=mac_address
        )
    
    async def release_ip(self, address_id: str) -> bool:
        return await self.delete_ip_address(address_id)

    # ========= Auto Discovery Helper =========
    
    async def auto_sync_discovered_ip(
        self,
        ip_address: str,
        hostname: str,
        mac_address: Optional[str] = None,
        is_interface: bool = False,
        device_mgmt_ip: Optional[str] = None,
        device_mgmt_phpipam_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Auto-book an IP in phpIPAM if it is discovered.
        Includes deduplication: If it's an interface IP but matches the device's Mgmt IP, 
        it just returns the device's phpipam_address_id without recreating.
        """
        if not ip_address or not self.enabled:
            return None
            
        # 1. Deduplication Check: Is this interface IP actually the management IP?
        if is_interface and device_mgmt_ip and ip_address == device_mgmt_ip:
            if device_mgmt_phpipam_id:
                return device_mgmt_phpipam_id
        
        try:
            # 2. Check if IP already exists in phpIPAM
            existing_ip = await self.search_ip(ip_address)
            if existing_ip and existing_ip.get("id"):
                return str(existing_ip.get("id"))
                
            # 3. If not found, try to find a subnet that matches the IP and allocate it
            target_ip = ipaddress.ip_address(ip_address)
            subnets = await self.get_subnets()
            
            for subnet in subnets:
                try:
                    network = ipaddress.ip_network(f"{subnet['subnet']}/{subnet['mask']}")
                    if target_ip in network:
                        # Create IP in this subnet
                        desc = "[Auto-Discovery] Interface IP" if is_interface else "[Auto-Discovery] Management IP"
                        new_ip = await self.create_ip_address(
                            subnet_id=str(subnet["id"]),
                            ip_address=ip_address,
                            hostname=hostname,
                            mac_address=mac_address,
                            description=f"{desc} for {hostname}"
                        )
                        if new_ip and new_ip.get("id"):
                            return str(new_ip.get("id"))
                except ValueError:
                    continue  # Ignore invalid subnets
        except Exception as e:
            print(f"[phpIPAM] Error auto-syncing IP {ip_address}: {e}")
            
        return None

    # ========= Smart Booking (with Notification) =========

    async def book_ip(
        self,
        ip_address: str,
        hostname: str,
        mac_address: Optional[str] = None,
        description: Optional[str] = None,
        subnet_id: Optional[str] = None,
        purpose: str = "Management IP",
        device_status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Smart IP booking with full notification support.
        Returns IpamResult-compatible dict:
        { success, code, phpipam_address_id, ip_address, subnet_info, error_message }

        Flow:
        1. phpIPAM disabled → IPAM_DISABLED
        2. Search IP → ถ้าเจอ → IPAM_ALREADY_EXISTS (reuse)
        3. ถ้ามี subnet_id → book ตรงใน subnet นั้น (Picker mode)
           ถ้าไม่มี → auto-find subnet ที่ match (Manual mode)
        4. Book IP → IPAM_BOOKED | IPAM_CONFLICT
        5. ไม่เจอ subnet → IPAM_NO_SUBNET
        """
        if not self.enabled:
            return {
                "success": False,
                "code": "IPAM_DISABLED",
                "ip_address": ip_address,
                "phpipam_address_id": None,
                "subnet_info": None,
                "error_message": "phpIPAM integration is not enabled"
            }

        if not ip_address:
            return {
                "success": False,
                "code": "IPAM_NO_SUBNET",
                "ip_address": None,
                "phpipam_address_id": None,
                "subnet_info": None,
                "error_message": "No IP address provided"
            }

        try:
            target_tag = "1"
            if device_status:
                status_str = device_status.value if hasattr(device_status, "value") else str(device_status)
                status_str = status_str.split('.')[-1].upper()
                target_tag = "1" if status_str == "ONLINE" else "2"

            # Step 1: Check if IP already exists in phpIPAM
            existing_ip = await self.search_ip(ip_address)
            if existing_ip and existing_ip.get("id"):
                existing_id = str(existing_ip.get("id"))
                
                # Get subnet info for notification
                subnet_info = None
                existing_subnet_id = existing_ip.get("subnetId")
                if existing_subnet_id:
                    subnet_data = await self.get_subnet(str(existing_subnet_id))
                    if subnet_data:
                        subnet_info = f"{subnet_data.get('subnet')}/{subnet_data.get('mask')}"

                # Update existing record with new hostname/MAC/tag → reactivate
                update_data = {"tag": target_tag, "state": target_tag}
                if hostname:
                    update_data["hostname"] = hostname
                if mac_address:
                    normalized = self._normalize_mac(mac_address)
                    if normalized:
                        update_data["mac"] = normalized
                if description:
                    update_data["description"] = description[:64]
                else:
                    update_data["description"] = f"[{purpose}] {hostname}"[:64]

                await self.update_ip_address(existing_id, **update_data)

                return {
                    "success": True,
                    "code": "IPAM_ALREADY_EXISTS",
                    "phpipam_address_id": existing_id,
                    "ip_address": ip_address,
                    "subnet_info": subnet_info,
                    "error_message": None
                }

            # Step 2: Find target subnet
            target_subnet_id = subnet_id
            target_subnet_info = None

            if target_subnet_id:
                # Picker mode: use the provided subnet_id directly
                subnet_data = await self.get_subnet(target_subnet_id)
                if subnet_data:
                    target_subnet_info = f"{subnet_data.get('subnet')}/{subnet_data.get('mask')}"
            else:
                # Manual mode: auto-find subnet that contains this IP.
                # We must pick the MOST SPECIFIC (longest prefix / smallest subnet)
                # match, not just the first one.  Otherwise a parent like /16
                # is chosen over a child like /24 simply because it appeared
                # earlier in the phpIPAM response.
                target_ip = ipaddress.ip_address(ip_address)
                subnets = await self.get_subnets()

                best_prefix_len = -1
                for subnet in subnets:
                    try:
                        network = ipaddress.ip_network(
                            f"{subnet['subnet']}/{subnet['mask']}", strict=False
                        )
                        if target_ip in network:
                            prefix_len = network.prefixlen
                            if prefix_len > best_prefix_len:
                                best_prefix_len = prefix_len
                                target_subnet_id = str(subnet["id"])
                                target_subnet_info = f"{subnet['subnet']}/{subnet['mask']}"
                    except (ValueError, KeyError):
                        continue

                if target_subnet_id:
                    print(f"[phpIPAM] Auto-selected subnet {target_subnet_info} (/{best_prefix_len}) for {ip_address}")

            if not target_subnet_id:
                return {
                    "success": False,
                    "code": "IPAM_NO_SUBNET",
                    "phpipam_address_id": None,
                    "ip_address": ip_address,
                    "subnet_info": None,
                    "error_message": f"No subnet found that contains IP {ip_address}"
                }

            # Step 3: Book IP in the target subnet
            desc = (description or f"[{purpose}] {hostname}")[:64]
            new_ip = await self.create_ip_address(
                subnet_id=target_subnet_id,
                ip_address=ip_address,
                hostname=hostname,
                mac_address=mac_address,
                description=desc,
                tag=target_tag,
                state=target_tag
            )

            if new_ip and new_ip.get("id"):
                new_id = str(new_ip.get("id"))
                # phpIPAM ignores tag during POST (defaults to 1=Used).
                # Explicitly PATCH to set the correct tag if device is not ONLINE.
                if target_tag != "1":
                    await self.update_ip_address(new_id, tag=target_tag, state=target_tag)
                    print(f"[phpIPAM] Post-create PATCH tag={target_tag} for {ip_address} (id={new_id})")

                return {
                    "success": True,
                    "code": "IPAM_BOOKED",
                    "phpipam_address_id": new_id,
                    "ip_address": ip_address,
                    "subnet_info": target_subnet_info,
                    "error_message": None
                }
            else:
                return {
                    "success": False,
                    "code": "IPAM_CONFLICT",
                    "phpipam_address_id": None,
                    "ip_address": ip_address,
                    "subnet_info": target_subnet_info,
                    "error_message": f"phpIPAM rejected IP {ip_address} — possible overlap or conflict"
                }

        except Exception as e:
            print(f"[phpIPAM] Error booking IP {ip_address}: {e}")
            return {
                "success": False,
                "code": "IPAM_CONFLICT",
                "phpipam_address_id": None,
                "ip_address": ip_address,
                "subnet_info": None,
                "error_message": str(e)
            }

    async def release_ip_safe(self, phpipam_address_id: str) -> Dict[str, Any]:
        """
        Retire IP in phpIPAM (soft release — เปลี่ยนเป็น Reserved เพื่อไม่ให้ใช้งานต่อเอง).
        
        เปลี่ยน tag เป็น 3 (Reserved) + ล้าง hostname
        ทำให้ IP ยังอยู่ใน phpIPAM (เห็นใน space map ว่า "Reserved")
        User สามารถเลือกใช้ซ้ำ หรือ admin จะลบ manual ก็ได้
        
        phpIPAM Tags: 1=Online, 2=Offline, 3=Reserved, 4=DHCP
        """
        if not self.enabled:
            return {
                "success": False,
                "code": "IPAM_DISABLED",
                "phpipam_address_id": phpipam_address_id,
                "ip_address": None,
                "subnet_info": None,
                "error_message": "phpIPAM integration is not enabled"
            }

        try:
            # Get IP info before updating (for notification message)
            ip_info = await self.get_ip_address(phpipam_address_id)
            ip_address = ip_info.get("ip") if ip_info else None
            old_hostname = ip_info.get("hostname", "") if ip_info else ""
            old_description = ip_info.get("description", "") if ip_info else ""

            # Soft release: set tag=2 (Offline), clear hostname, mark description
            from datetime import datetime
            release_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            release_desc = f"[Released {release_timestamp}] was: {old_hostname}"[:64]
            updated = await self.update_ip_address(
                phpipam_address_id,
                tag="3",  # phpIPAM tag 3 = Reserved
                state="3", # Support for environments expecting state
                hostname="",  # ล้าง hostname — แสดงว่าไม่มี device ใช้อยู่
                description=release_desc,
                mac=""  # ล้าง MAC — ไม่ผูกกับ device แล้ว
            )

            if updated:
                return {
                    "success": True,
                    "code": "IPAM_RELEASED",
                    "phpipam_address_id": phpipam_address_id,
                    "ip_address": ip_address,
                    "subnet_info": None,
                    "error_message": None
                }
            else:
                return {
                    "success": False,
                    "code": "IPAM_RELEASE_FAILED",
                    "phpipam_address_id": phpipam_address_id,
                    "ip_address": ip_address,
                    "subnet_info": None,
                    "error_message": f"Failed to retire IP {phpipam_address_id} in phpIPAM"
                }
        except Exception as e:
            print(f"[phpIPAM] Error retiring IP {phpipam_address_id}: {e}")
            return {
                "success": False,
                "code": "IPAM_RELEASE_FAILED",
                "phpipam_address_id": phpipam_address_id,
                "ip_address": None,
                "subnet_info": None,
                "error_message": str(e)
            }

    # ========= Device Status → phpIPAM Sync (centralized) =========

    async def sync_device_status_to_ipam(
        self,
        device_id: str,
        new_status: str,
    ) -> None:
        """
        Sync device ONLINE/OFFLINE status → phpIPAM tag for all IPs belonging to this device.

        This is a fire-and-forget helper that any service can call after changing
        DeviceNetwork.status in the DB. It will:
          1. Look up the device's phpipam_address_id (Management IP)
          2. Look up the device's netconf_host (if different from ip_address)
          3. PATCH each phpIPAM record's tag to match the new status

        phpIPAM Tags: 1=Used (Online), 2=Offline, 3=Reserved

        Args:
            device_id: DB primary key of the DeviceNetwork record
            new_status: "ONLINE" or "OFFLINE" (case-insensitive)
        """
        if not self.enabled:
            return

        try:
            from app.database import get_prisma_client
            prisma = get_prisma_client()

            device = await prisma.devicenetwork.find_unique(where={"id": device_id})
            if not device:
                return

            # Normalize status string (handles Enum or plain str)
            status_str = new_status.value if hasattr(new_status, "value") else str(new_status)
            status_str = status_str.split(".")[-1].upper()
            target_tag = "1" if status_str == "ONLINE" else "2"

            # 1. Management IP (tracked via phpipam_address_id)
            if device.phpipam_address_id:
                try:
                    await self.update_ip_address(
                        device.phpipam_address_id,
                        tag=target_tag,
                        state=target_tag,
                    )
                    print(f"[phpIPAM-sync] device={device.device_name} mgmt_ip tag→{target_tag}")
                except Exception as e:
                    print(f"[phpIPAM-sync] Failed to update mgmt IP for {device.device_name}: {e}")

            # 2. Netconf Host IP (if different from Management IP, looked up dynamically)
            if device.netconf_host and device.netconf_host != device.ip_address:
                try:
                    nc_obj = await self.search_ip(device.netconf_host)
                    if nc_obj and nc_obj.get("id"):
                        await self.update_ip_address(
                            str(nc_obj["id"]),
                            tag=target_tag,
                            state=target_tag,
                        )
                        print(f"[phpIPAM-sync] device={device.device_name} netconf_ip tag→{target_tag}")
                except Exception as e:
                    print(f"[phpIPAM-sync] Failed to update netconf IP for {device.device_name}: {e}")

        except Exception as e:
            # Never let IPAM sync break the calling service
            print(f"[phpIPAM-sync] Error syncing device {device_id}: {e}")

    # ========= Picker Data (for Frontend Dropdown) =========

    async def get_subnets_for_picker(self) -> List[Dict[str, Any]]:
        """
        Return subnet list with usage info for dropdown picker.
        Each item: { id, label, subnet, mask, description, usage_percent, free_hosts, total_hosts }
        """
        if not self.enabled:
            return []

        try:
            subnets = await self.get_subnets()
            picker_items = []

            for subnet in subnets:
                subnet_id = str(subnet.get("id"))
                subnet_addr = subnet.get("subnet", "")
                mask = subnet.get("mask", "")
                description = subnet.get("description", "")

                # Get usage info
                usage = await self.get_subnet_usage(subnet_id)

                free_hosts = 0
                total_hosts = 0
                usage_percent = 0.0

                if usage:
                    free_hosts = int(usage.get("freehosts", 0))
                    total_hosts = int(usage.get("maxhosts", 0))
                    usage_percent = float(usage.get("Used_percent", 0))

                # Build readable label
                desc_part = f" — {description}" if description else ""
                label = f"{subnet_addr}/{mask}{desc_part} ({free_hosts} free)"

                picker_items.append({
                    "id": subnet_id,
                    "label": label,
                    "subnet": subnet_addr,
                    "mask": mask,
                    "description": description,
                    "usage_percent": usage_percent,
                    "free_hosts": free_hosts,
                    "total_hosts": total_hosts,
                })

            return picker_items

        except Exception as e:
            print(f"[phpIPAM] Error getting subnets for picker: {e}")
            return []

    async def get_available_ips(self, subnet_id: str, limit: int = 100) -> Dict[str, Any]:
        """
        Calculate free IPs in a subnet.
        IP ว่าง = ทั้ง IP ที่ไม่มี record + IP ที่ถูก retire แล้ว (tag=2 Offline)
        Returns: { subnet_id, subnet, available_ips: [...], total_available }
        """
        if not self.enabled:
            return {"subnet_id": subnet_id, "subnet": "", "available_ips": [], "total_available": 0}

        try:
            # Get subnet info
            subnet_data = await self.get_subnet(subnet_id)
            if not subnet_data:
                return {"subnet_id": subnet_id, "subnet": "", "available_ips": [], "total_available": 0}

            subnet_addr = subnet_data.get("subnet", "")
            mask = subnet_data.get("mask", "")
            network = ipaddress.ip_network(f"{subnet_addr}/{mask}", strict=False)

            # Get existing addresses — only actively used IPs block availability
            existing_addresses = await self.get_subnet_addresses(subnet_id)
            
            # IPs ที่ "ใช้อยู่จริง" = tag=1 (Online), tag=3 (Reserved), gateway
            # IPs ที่ tag=2 (Offline/retired) ถือว่า "ว่าง" เลือกได้
            actively_used_ips = set()
            for addr in existing_addresses:
                ip = addr.get("ip")
                if not ip:
                    continue
                tag = str(addr.get("tag", "1"))
                is_gw = addr.get("is_gateway") in (1, "1", True)
                if is_gw or tag in ("1", "3"):  # Online, Reserved, Gateway
                    actively_used_ips.add(ip)

            # Calculate free IPs (skip network address, broadcast, and actively used IPs)
            available_ips = []
            for host in network.hosts():
                ip_str = str(host)
                if ip_str not in actively_used_ips:
                    available_ips.append(ip_str)
                    if len(available_ips) >= limit:
                        break

            return {
                "subnet_id": subnet_id,
                "subnet": f"{subnet_addr}/{mask}",
                "available_ips": available_ips,
                "total_available": len(available_ips),
            }

        except Exception as e:
            print(f"[phpIPAM] Error getting available IPs for subnet {subnet_id}: {e}")
            return {"subnet_id": subnet_id, "subnet": "", "available_ips": [], "total_available": 0}

    async def get_space_map(
        self,
        subnet_id: str,
        offset: int = 0,
        limit: int = 256
    ) -> Dict[str, Any]:
        """
        Return paginated visual space map for a subnet.
        Only generates the slice [offset, offset+limit) of host IPs, keeping
        memory and payload small even for huge subnets like /18 (16k hosts).

        Returns:
            { subnet_id, subnet, mask, total_hosts, used, free,
              offset, limit, has_more, addresses: [...] }
        """
        empty = {
            "subnet_id": subnet_id, "subnet": "", "mask": "",
            "total_hosts": 0, "used": 0, "free": 0,
            "offset": offset, "limit": limit, "has_more": False,
            "addresses": []
        }

        if not self.enabled:
            return empty

        try:
            # Get subnet info
            subnet_data = await self.get_subnet(subnet_id)
            if not subnet_data:
                return empty

            subnet_addr = subnet_data.get("subnet", "")
            mask = subnet_data.get("mask", "")
            network = ipaddress.ip_network(f"{subnet_addr}/{mask}", strict=False)

            # Total usable hosts (excludes network + broadcast)
            total_hosts = max(network.num_addresses - 2, 0)
            if total_hosts == 0:
                return {**empty, "subnet": subnet_addr, "mask": mask}

            # Get existing addresses from phpIPAM (single API call, cached by phpIPAM)
            existing_addresses = await self.get_subnet_addresses(subnet_id)
            used_map: Dict[str, Dict] = {}

            for addr in existing_addresses:
                ip = addr.get("ip")
                if not ip:
                    continue
                is_gw = addr.get("is_gateway") in (1, "1", True)

                raw_tag = addr.get("tag", "1")
                if isinstance(raw_tag, dict):
                    tag = str(raw_tag.get("id", "1"))
                else:
                    tag = str(raw_tag)

                if tag == "1":
                    tag_id_field = addr.get("tagId")
                    if tag_id_field and str(tag_id_field) != "1":
                        tag = str(tag_id_field)

                if is_gw:
                    status = "gateway"
                elif tag == "3":
                    status = "reserved"
                elif tag == "2":
                    status = "offline"
                elif tag == "4":
                    status = "dhcp"
                else:
                    status = "used"

                used_map[ip] = {
                    "ip": ip,
                    "status": status,
                    "tag": tag,
                    "hostname": addr.get("hostname"),
                    "description": addr.get("description"),
                    "address_id": str(addr.get("id", "")),
                    "mac": addr.get("mac"),
                }

            used_count = len(used_map)

            # Build paginated slice — skip first `offset` hosts, take `limit`
            addresses = []
            idx = 0
            end = offset + limit
            has_more = False

            for host in network.hosts():
                if idx >= end:
                    has_more = True
                    break
                if idx >= offset:
                    ip_str = str(host)
                    if ip_str in used_map:
                        addresses.append(used_map[ip_str])
                    else:
                        addresses.append({
                            "ip": ip_str,
                            "status": "free",
                            "tag": None,
                            "hostname": None,
                            "description": None,
                            "address_id": None,
                            "mac": None,
                        })
                idx += 1

            return {
                "subnet_id": subnet_id,
                "subnet": subnet_addr,
                "mask": mask,
                "total_hosts": total_hosts,
                "used": used_count,
                "free": total_hosts - used_count,
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
                "addresses": addresses,
            }

        except Exception as e:
            print(f"[phpIPAM] Error getting space map for subnet {subnet_id}: {e}")
            return empty

