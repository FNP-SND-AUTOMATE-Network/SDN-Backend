from pydantic import BaseModel
from typing import Dict, Optional

class DeviceProfile(BaseModel):
    """
    Device Profile สำหรับเก็บข้อมูล device ที่ mount ใน ODL
    
    Attributes:
        device_id: Unique identifier for the device
        node_id: ODL node id in topology-netconf
        vendor: Device vendor ("cisco" | "huawei")
        model: Device model (optional)
        role: Device role ("router" | "switch")
        default_strategy: Strategy for selecting YANG driver
        oc_supported_intents: Map of intent->bool for OpenConfig support
    
    Strategy Options:
        - "operation-based" (default): GET→OpenConfig, PUT/POST→Vendor YANG
        - "oc-first": Try OpenConfig first, fallback to vendor
        - "vendor-first": Try vendor YANG first, fallback to OpenConfig
    """
    device_id: str
    node_id: str            # ODL node id in topology-netconf
    vendor: str             # "cisco" | "huawei"
    model: Optional[str] = None
    role: str = "router"    # router | switch
    default_strategy: str = "operation-based"  # operation-based | oc-first | vendor-first
    oc_supported_intents: Dict[str, bool] = {}

