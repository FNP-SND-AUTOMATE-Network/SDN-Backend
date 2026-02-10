"""
NBI Interface Discovery Endpoints
ดึง interface list จาก device เพื่อให้ Frontend แสดง dropdown
"""
from fastapi import APIRouter, HTTPException, Query
from app.services.interface_discovery_service import InterfaceDiscoveryService
from app.services.device_profile_service_db import DeviceProfileService
from app.core.logging import logger

router = APIRouter()
discovery_service = InterfaceDiscoveryService()
device_service = DeviceProfileService()


@router.get(
    "/devices/{device_id}/interfaces/discover",
    summary="Discover interfaces from device",
    description="ดึง interface list จาก device ผ่าน ODL ใช้สำหรับ dropdown ให้ user เลือก interface",
)
async def discover_interfaces(
    device_id: str,
    force_refresh: bool = Query(False, description="Force refresh cache"),
):
    """
    Discover all interfaces on a device.
    
    Returns:
    - interfaces: list of interface details (name, type, IP, status, etc.)
    - count: total interface count
    - cached: whether result came from cache
    
    Example response:
    {
        "success": true,
        "node_id": "CSR1000vT",
        "count": 5,
        "interfaces": [
            {
                "name": "GigabitEthernet1",
                "type": "GigabitEthernet",
                "number": "1",
                "description": "Management",
                "admin_status": "up",
                "ipv4": "192.168.1.10 (255.255.255.0)",
                "ipv6": null,
                "mtu": null,
                "has_ospf": false
            }
        ]
    }
    """
    try:
        # Resolve device → get node_id and vendor
        device = await device_service.get_device(device_id)
        if not device:
            raise HTTPException(
                status_code=404,
                detail={"error": "DEVICE_NOT_FOUND", "message": f"Device '{device_id}' not found"},
            )

        node_id = device.get("node_id", device_id)
        vendor = device.get("vendor", "cisco")

        interfaces = await discovery_service.discover(
            node_id=node_id,
            vendor=vendor,
            force_refresh=force_refresh,
        )

        return {
            "success": True,
            "node_id": node_id,
            "vendor": vendor,
            "count": len(interfaces),
            "interfaces": interfaces,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Interface discovery failed for {device_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail={"error": "DISCOVERY_FAILED", "message": str(e)},
        )


@router.get(
    "/devices/{device_id}/interfaces/names",
    summary="Get interface name list",
    description="ดึงเฉพาะชื่อ interface สำหรับ dropdown",
)
async def get_interface_names(
    device_id: str,
    force_refresh: bool = Query(False, description="Force refresh cache"),
):
    """
    Get only interface names for dropdown.
    
    Returns:
    {
        "success": true,
        "node_id": "CSR1000vT",
        "names": ["GigabitEthernet1", "GigabitEthernet2", "Loopback0"]
    }
    """
    try:
        device = await device_service.get_device(device_id)
        if not device:
            raise HTTPException(
                status_code=404,
                detail={"error": "DEVICE_NOT_FOUND", "message": f"Device '{device_id}' not found"},
            )

        node_id = device.get("node_id", device_id)
        vendor = device.get("vendor", "cisco")

        names = await discovery_service.get_interface_names(
            node_id=node_id,
            vendor=vendor,
            force_refresh=force_refresh,
        )

        return {
            "success": True,
            "node_id": node_id,
            "count": len(names),
            "names": names,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Interface name discovery failed for {device_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail={"error": "DISCOVERY_FAILED", "message": str(e)},
        )


@router.delete(
    "/devices/{device_id}/interfaces/cache",
    summary="Invalidate interface cache",
    description="ล้าง cache interface list ของ device",
)
async def invalidate_cache(device_id: str):
    """Invalidate cached interfaces for a device"""
    try:
        device = await device_service.get_device(device_id)
        node_id = device.get("node_id", device_id) if device else device_id

        discovery_service.invalidate(node_id)

        return {
            "success": True,
            "message": f"Cache invalidated for {node_id}",
        }
    except Exception as e:
        logger.error(f"Cache invalidation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
