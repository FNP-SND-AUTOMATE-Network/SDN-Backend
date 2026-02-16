"""
Device Profile Schema

Terminology:
-----------
- device_id: Database UUID (primary key, internal use)
- node_id: ODL topology-netconf identifier (used in RESTCONF paths)
           This is what API clients send as 'deviceId' in requests.
"""
from pydantic import BaseModel
from typing import Dict, Optional


class DeviceProfile(BaseModel):
    """
    Device Profile for NBI Intent processing.
    
    Attributes:
        device_id: Database UUID (internal primary key)
        node_id: ODL node identifier - same as 'deviceId' in API requests
        vendor: Device vendor ("cisco" | "huawei" | "juniper" | "arista")
        model: Device model (optional)
        role: Device role ("router" | "switch")
        default_strategy: YANG driver selection strategy
        oc_supported_intents: Map of intent->bool for OpenConfig support
    
    Strategy Options:
        - "operation-based" (default): GET→OpenConfig, PUT/POST→Vendor YANG
        - "oc-first": Try OpenConfig first, fallback to vendor
        - "vendor-first": Try vendor YANG first, fallback to OpenConfig
    
    Note:
        - API uses 'deviceId' = database 'node_id' (same value)
        - 'device_id' is internal UUID, not exposed to API clients
    """
    device_id: str              # Database UUID (internal)
    node_id: str                # ODL node identifier = API 'deviceId'
    vendor: str                 # "cisco" | "huawei" | etc.
    model: Optional[str] = None
    role: str = "router"        # router | switch
    default_strategy: str = "operation-based"  # operation-based | oc-first | vendor-first
    oc_supported_intents: Dict[str, bool] = {}
