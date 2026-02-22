"""
NBI Interface Discovery Endpoints
ดึง interface list จาก device เพื่อให้ Frontend แสดง dropdown
"""
from fastapi import APIRouter, HTTPException, Query
from app.services.interface_discovery_service import InterfaceDiscoveryService
from app.services.device_profile_service_db import DeviceProfileService
from app.core.logging import logger
from app.database import get_prisma_client

router = APIRouter()
discovery_service = InterfaceDiscoveryService()
device_service = DeviceProfileService()


@router.get(
    "/devices/{node_id}/interfaces/discover",
    summary="Discover interfaces from device",
    description="ดึง interface list จาก device ผ่าน ODL ใช้สำหรับ dropdown ให้ user เลือก interface",
)
async def discover_interfaces(
    node_id: str,
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
        # Resolve device → get vendor from node_id
        device = await device_service.get(node_id)
        if not device:
            raise HTTPException(
                status_code=404,
                detail={"error": "DEVICE_NOT_FOUND", "message": f"Device '{node_id}' not found"},
            )

        vendor = device.os_type or device.vendor or "cisco"

        interfaces = await discovery_service.discover(
            node_id=device.node_id,
            vendor=vendor,
            force_refresh=force_refresh,
        )

        # ==========================================
        # Sync discovered interfaces into Prisma DB
        # ==========================================
        prisma = get_prisma_client()
        try:
            db_device_id = device.device_id
            for intf in interfaces:
                intf_name = intf.get("name")
                if intf_name:
                    tp_id = f"{node_id}:{intf_name}"
                    description = intf.get("description") or ""
                    admin_status = "UP" if intf.get("admin_status") == "up" else "DOWN"
                    
                    ipv4_addr = intf.get("ipv4_address")
                    subnet_mask = intf.get("subnet_mask")
                    mac_address = intf.get("mac_address")
                    
                    # Parse port number
                    port_num_str = intf.get("number")
                    port_number = None
                    if port_num_str and str(port_num_str).isdigit():
                        port_number = int(port_num_str)
                    
                    # Parse InterfaceType Enum
                    raw_type = intf.get("type", "").lower()
                    if "loopback" in raw_type:
                        intf_type = "LOOPBACK"
                    elif "vlan" in raw_type:
                        intf_type = "VLAN"
                    elif "tunnel" in raw_type:
                        intf_type = "TUNNEL"
                    elif "virtual" in raw_type:
                        intf_type = "VIRTUAL"
                    elif "ethernet" in raw_type or "fast" in raw_type or "gigabit" in raw_type or "port-channel" in raw_type:
                        intf_type = "PHYSICAL"
                    else:
                        intf_type = "OTHER"

                    # Handle Interface Upsert
                    intf_record = await prisma.interface.find_first(
                        where={"device_id": db_device_id, "name": intf_name}
                    )
                    
                    if intf_record:
                        await prisma.interface.update(
                            where={"id": intf_record.id},
                            data={
                                "tp_id": tp_id,
                                "description": description,
                                "status": admin_status,
                                "ip_address": ipv4_addr,
                                "subnet_mask": subnet_mask,
                                "mac_address": mac_address,
                                "port_number": port_number,
                                "type": intf_type
                            }
                        )
                    else:
                        await prisma.interface.create(
                            data={
                                "device_id": db_device_id,
                                "name": intf_name,
                                "tp_id": tp_id,
                                "description": description,
                                "status": admin_status,
                                "ip_address": ipv4_addr,
                                "subnet_mask": subnet_mask,
                                "mac_address": mac_address,
                                "port_number": port_number,
                                "type": intf_type
                            }
                        )
        except Exception as db_e:
            import traceback
            traceback.print_exc()
            logger.error(f"Failed to sync discovered interfaces to DB for {node_id}: {db_e}")

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
        logger.error(f"Interface discovery failed for {node_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail={"error": "DISCOVERY_FAILED", "message": str(e)},
        )


@router.get(
    "/devices/{node_id}/interfaces/names",
    summary="Get interface name list",
    description="ดึงเฉพาะชื่อ interface สำหรับ dropdown",
)
async def get_interface_names(
    node_id: str,
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
        device = await device_service.get(node_id)
        if not device:
            raise HTTPException(
                status_code=404,
                detail={"error": "DEVICE_NOT_FOUND", "message": f"Device '{node_id}' not found"},
            )

        vendor = device.os_type or device.vendor or "cisco"

        names = await discovery_service.get_interface_names(
            node_id=device.node_id,
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
        logger.error(f"Interface name discovery failed for {node_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail={"error": "DISCOVERY_FAILED", "message": str(e)},
        )


@router.delete(
    "/devices/{node_id}/interfaces/cache",
    summary="Invalidate interface cache",
    description="ล้าง cache interface list ของ device",
)
async def invalidate_cache(node_id: str):
    """Invalidate cached interfaces for a device"""
    try:
        discovery_service.invalidate(node_id)

        return {
            "success": True,
            "message": f"Cache invalidated for {node_id}",
        }
    except Exception as e:
        logger.error(f"Cache invalidation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
