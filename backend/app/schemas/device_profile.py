from pydantic import BaseModel
from typing import Dict, Optional

class DeviceProfile(BaseModel):
    device_id: str
    node_id: str            # ODL node id in topology-netconf
    vendor: str             # "cisco" | "huawei"
    model: Optional[str] = None
    role: str = "router"    # router | switch
    default_strategy: str = "oc-first"  # oc-first | vendor-first
    oc_supported_intents: Dict[str, bool] = {}
