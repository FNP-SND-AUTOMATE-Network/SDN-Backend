from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

class IntentRequest(BaseModel):
    intent: str = Field(..., examples=["interface.set_ipv4", "show.interface"])
    deviceId: str = Field(..., examples=["CSR1", "NE40E1"])
    params: Dict[str, Any] = Field(default_factory=dict)

class IntentResponse(BaseModel):
    success: bool
    intent: str
    deviceId: str
    strategy_used: str
    driver_used: str
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None
