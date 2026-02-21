"""
Device Profile Schema

Terminology:
-----------
- device_id: Database UUID (primary key, internal use)
- node_id: ODL topology-netconf identifier (used in RESTCONF paths)
           This is what API clients send as 'deviceId' in requests.
"""
from pydantic import BaseModel
from typing import Optional


class DeviceProfile(BaseModel):
    """
    Device Profile for NBI Intent processing.
    
    Attributes:
        device_id: Database UUID (internal primary key)
        node_id: ODL node identifier - same as 'deviceId' in API requests
        vendor: Device vendor ("cisco" | "huawei" | "juniper" | "arista")
        model: Device model (optional)
        role: Device role ("router" | "switch")
    
    Note:
        - API uses 'deviceId' = database 'node_id' (same value)
        - 'device_id' is internal UUID, not exposed to API clients
        - Driver selection is based on vendor directly (no strategy needed)
    """
    device_id: str              # Database UUID (internal)
    node_id: str                # ODL node identifier = API 'deviceId'
    vendor: str                 # "cisco" | "huawei" | etc. (Legacy, still used for some logic)
    os_type: Optional[str] = None # "CISCO_IOS_XE" | "HUAWEI_VRP" | "CISCO_IOS" | "CISCO_NXOS" | etc.
    model: Optional[str] = None
    role: str = "router"        # router | switch
