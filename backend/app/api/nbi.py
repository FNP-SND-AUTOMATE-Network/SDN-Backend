"""
NBI (Northbound Interface) API
Intent-Based API สำหรับ Network Operations
"""
from typing import Dict, List, Any
from fastapi import APIRouter
from app.schemas.intent import IntentRequest, IntentResponse
from app.services.intent_service import IntentService
from app.services.device_profile_service import DeviceProfileService
from app.core.intent_registry import IntentRegistry

router = APIRouter(prefix="/api/v1/nbi", tags=["NBI"])
intent_service = IntentService()
device_service = DeviceProfileService()


# ===== Intent Endpoints =====

@router.post("/intent", response_model=IntentResponse)
async def handle_intent(req: IntentRequest):
    """
    Execute an Intent-based network operation
    
    Intent format: `category.action` (e.g., `interface.set_ipv4`, `show.interface`)
    
    Example Request:
    ```json
    {
        "intent": "show.interface",
        "deviceId": "CSR1",
        "params": {
            "interface": "GigabitEthernet1"
        }
    }
    ```
    """
    return await intent_service.handle(req)


# ===== Discovery Endpoints =====

@router.get("/intents", response_model=Dict[str, List[str]])
async def list_supported_intents():
    """
    Get all supported intents grouped by category
    
    Returns:
    ```json
    {
        "interface": ["interface.set_ipv4", "interface.enable", ...],
        "show": ["show.interface", "show.interfaces", ...],
        "routing": ["routing.static.add", ...],
        "system": ["system.set_hostname", ...]
    }
    ```
    """
    return IntentRegistry.get_supported_intents()


@router.get("/intents/{intent_name}")
async def get_intent_info(intent_name: str):
    """
    Get detailed information about a specific intent
    
    Returns required params, description, etc.
    """
    intent = IntentRegistry.get(intent_name)
    if not intent:
        return {"error": f"Intent not found: {intent_name}"}
    
    return {
        "name": intent.name,
        "category": intent.category.value,
        "description": intent.description,
        "required_params": intent.required_params,
        "optional_params": intent.optional_params,
        "is_read_only": intent.is_read_only,
    }


@router.get("/devices")
async def list_devices():
    """
    Get all registered devices
    
    Returns device profiles with their capabilities
    """
    devices = device_service.list_all()
    return {
        "devices": [
            {
                "device_id": d.device_id,
                "node_id": d.node_id,
                "vendor": d.vendor,
                "model": d.model,
                "role": d.role,
                "default_strategy": d.default_strategy,
            }
            for d in devices
        ],
        "total": len(devices)
    }


@router.get("/devices/{device_id}")
async def get_device_info(device_id: str):
    """
    Get detailed information about a specific device
    
    Includes supported intents and capabilities
    """
    device = device_service.get(device_id)
    return {
        "device_id": device.device_id,
        "node_id": device.node_id,
        "vendor": device.vendor,
        "model": device.model,
        "role": device.role,
        "default_strategy": device.default_strategy,
        "oc_supported_intents": device.oc_supported_intents,
    }


@router.get("/devices/{device_id}/capabilities")
async def get_device_capabilities(device_id: str):
    """
    Get intent capabilities for a specific device
    
    Shows which intents are supported via OpenConfig
    """
    device = device_service.get(device_id)
    
    # Group intents by support status
    oc_supported = []
    vendor_only = []
    
    for intent_name, oc_ok in device.oc_supported_intents.items():
        if oc_ok:
            oc_supported.append(intent_name)
        else:
            vendor_only.append(intent_name)
    
    return {
        "device_id": device_id,
        "vendor": device.vendor,
        "default_strategy": device.default_strategy,
        "openconfig_supported": oc_supported,
        "vendor_only": vendor_only,
    }
