import httpx
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta


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
        if mac_address:
            data["mac"] = mac_address
        
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
