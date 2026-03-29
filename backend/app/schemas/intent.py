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
from typing import Any, Dict, List, Optional
from enum import Enum


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


# ========= Bulk Intent Schemas =========

class BulkIntentStatus(str, Enum):
    """Status of each intent in a bulk request"""
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"  # Skipped due to earlier failure (Fail-Fast)


class IntentBulkRequest(BaseModel):
    """
    Bulk Intent API Request
    
    Allows submitting multiple intents to be executed sequentially on the device.
    Uses Fail-Fast: if one intent fails, remaining intents are cancelled.
    
    Attributes:
        intents: Ordered list of intent requests to execute
    """
    intents: List[IntentRequest] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Ordered list of intent requests (max 50)"
    )


class BulkIntentItemResult(BaseModel):
    """
    Result of a single intent within a bulk request
    """
    index: int = Field(description="0-based position in the original request list")
    status: BulkIntentStatus
    intent: str
    node_id: str
    driver_used: Optional[str] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class IntentBulkResponse(BaseModel):
    """
    Bulk Intent API Response
    
    Attributes:
        success: True only if ALL intents succeeded
        total: Total number of intents submitted
        succeeded: Count of successfully executed intents
        failed: Count of failed intents (0 or 1 in Fail-Fast)
        cancelled: Count of intents skipped due to Fail-Fast abort
        results: Per-intent result details
    """
    success: bool
    total: int
    succeeded: int
    failed: int
    cancelled: int
    results: List[BulkIntentItemResult]
