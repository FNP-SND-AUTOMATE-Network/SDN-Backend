from pydantic import BaseModel, Field, IPvAnyAddress
from typing import Optional, List, Union
from datetime import datetime


# ========= Subnet Models =========

class SubnetResponse(BaseModel):
    id: str
    subnet: Optional[str] = None  # e.g., "192.168.1.0" - can be None in some cases
    mask: Optional[str] = None    # e.g., "24" - can be None in some cases
    description: Optional[str] = None
    section_id: Optional[str] = None
    vlan_id: Optional[str] = None
    master_subnet_id: Optional[str] = None  # Parent subnet ID (for nested subnets)


class SubnetListResponse(BaseModel):
    subnets: List[SubnetResponse]
    total: int


# ========= IP Address Models =========

class IpAddressCreateRequest(BaseModel):
    subnet_id: str
    ip_address: str  # Required - specific IP to create
    hostname: Optional[str] = None
    description: Optional[str] = None
    mac_address: Optional[str] = None
    is_gateway: Optional[int] = None  # 0 or 1
    tag: Optional[int] = None  # phpIPAM tag ID


class IpAddressAssignRequest(BaseModel):
    subnet_id: str
    ip_address: Optional[str] = None  # ถ้าไม่ระบุ จะ auto-assign
    hostname: Optional[str] = None
    description: Optional[str] = None
    mac_address: Optional[str] = None


class IpAddressUpdateRequest(BaseModel):
    hostname: Optional[str] = None
    description: Optional[str] = None
    mac_address: Optional[str] = None
    is_gateway: Optional[int] = None  # 0 or 1
    tag: Optional[int] = None



class IpAddressDetailResponse(BaseModel):
    id: str
    ip: str
    subnet_id: str
    hostname: Optional[str] = None
    description: Optional[str] = None
    mac: Optional[str] = None
    is_gateway: Optional[Union[str, int]] = None  # Can be 0/1 or "0"/"1"
    tag: Optional[Union[str, int]] = None  # Can be int or string


class IpAddressResponse(BaseModel):
    id: str
    ip: str
    subnet_id: str
    hostname: Optional[str] = None
    description: Optional[str] = None
    mac: Optional[str] = None
    phpipam_id: Optional[str] = None  # Internal phpIPAM ID


class IpAddressListResponse(BaseModel):
    addresses: List[IpAddressResponse]
    total: int


# ========= Device/Interface IP Assignment Models =========

class DeviceIpAssignRequest(BaseModel):
    subnet_id: str
    description: Optional[str] = None


class InterfaceIpAssignRequest(BaseModel):
    subnet_id: str
    description: Optional[str] = None


class IpAssignmentResponse(BaseModel):
    message: str
    ip_address: str
    subnet_id: str
    phpipam_address_id: str
    device_id: Optional[str] = None
    interface_id: Optional[str] = None


# ========= Sync Models =========

class SyncRequest(BaseModel):
    sync_devices: bool = True
    sync_interfaces: bool = True


class SyncResponse(BaseModel):
    message: str
    devices_synced: int
    interfaces_synced: int
    errors: List[str] = []


# ========= Subnet CRUD Models =========

class SubnetCreateRequest(BaseModel):
    subnet: str                          # IP address (e.g., "10.10.5.0")
    mask: str                            # Subnet mask (e.g., "24")
    section_id: str                      # Section ID (required)
    description: Optional[str] = None
    vlan_id: Optional[str] = None
    master_subnet_id: Optional[str] = None  # Parent subnet for nested subnets
    permissions: Optional[str] = None
    show_name: Optional[bool] = None
    dns_recursive: Optional[bool] = None
    dns_records: Optional[bool] = None
    allow_requests: Optional[bool] = None
    scan_agent: Optional[str] = None


class SubnetUpdateRequest(BaseModel):
    subnet: Optional[str] = None
    mask: Optional[str] = None
    description: Optional[str] = None
    vlan_id: Optional[str] = None
    master_subnet_id: Optional[str] = None
    permissions: Optional[str] = None
    show_name: Optional[bool] = None
    dns_recursive: Optional[bool] = None
    dns_records: Optional[bool] = None
    allow_requests: Optional[bool] = None
    scan_agent: Optional[str] = None


class SubnetDetailResponse(BaseModel):
    id: str
    subnet: str
    mask: str
    section_id: str
    description: Optional[str] = None
    vlan_id: Optional[str] = None
    master_subnet_id: Optional[str] = None
    permissions: Optional[str] = None
    show_name: Optional[Union[str, int]] = None  # Can be 0/1 or "0"/"1"


class SubnetUsageResponse(BaseModel):
    used: int
    maxhosts: int
    freehosts: int
    freehosts_percent: float
    Offline_percent: Optional[float] = None
    Used_percent: float
    Reserved_percent: Optional[float] = None



# ========= Sections Models =========

class SectionCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    master_section: Optional[str] = None  # Parent section for nested sections
    permissions: Optional[str] = None
    strict_mode: Optional[str] = None
    subnet_ordering: Optional[str] = None
    order: Optional[str] = None
    show_vlan_in_subnet_listing: Optional[bool] = None
    show_vrf_in_subnet_listing: Optional[bool] = None


class SectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    master_section: Optional[str] = None
    permissions: Optional[str] = None
    strict_mode: Optional[str] = None
    subnet_ordering: Optional[str] = None
    order: Optional[str] = None
    show_vlan_in_subnet_listing: Optional[bool] = None
    show_vrf_in_subnet_listing: Optional[bool] = None


class SectionResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    master_section: Optional[str] = None
    permissions: Optional[str] = None
    strict_mode: Optional[str] = None
    subnet_ordering: Optional[str] = None
    order: Optional[str] = None
    show_vlan_in_subnet_listing: Optional[Union[str, int]] = None  # Can be 0/1 or "0"/"1"
    show_vrf_in_subnet_listing: Optional[Union[str, int]] = None   # Can be 0/1 or "0"/"1"


class SectionListResponse(BaseModel):
    sections: List[SectionResponse]
    total: int
