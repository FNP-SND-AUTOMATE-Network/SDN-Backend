"""
Intent Schemas for NBI API

Terminology:
-----------
- node_id: The device identifier used in API and database.
           ODL topology-netconf node identifier (URL-safe).
           Example: "CSR1000vT", "Router-Core-01"

- device_id (DB): Database primary key (UUID).
                  For internal use only, not exposed in NBI API.
"""
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional


class IntentRequest(BaseModel):
    """
    Intent API Request
    
    Attributes:
        intent: Intent action (e.g., "show.interface", "interface.set_ipv4")
        node_id: ODL device identifier (URL-safe, matches database node_id)
        params: Intent-specific parameters
    """
    intent: str = Field(..., examples=["interface.set_ipv4", "show.interface"])
    node_id: str = Field(
        ..., 
        examples=["CSR1000vT", "Router-Core-01"],
        description="ODL device identifier. Used in RESTCONF mount path."
    )
    params: Dict[str, Any] = Field(default_factory=dict)


class IntentResponse(BaseModel):
    """
    Intent API Response
    
    Attributes:
        success: True if intent executed successfully
        intent: The executed intent
        node_id: ODL device identifier (same as request)
        driver_used: Driver that was used (cisco, huawei, etc.)
        result: Intent execution result
        error: Error details if success=False
    """
    success: bool
    intent: str
    node_id: str = Field(description="ODL device identifier")
    driver_used: str
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None
