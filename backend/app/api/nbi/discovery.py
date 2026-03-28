"""
NBI Interface Discovery Endpoints

Two-tier interface data strategy:
  Tier 1 (Fast)  — GET /interfaces/cached   → อ่านจาก DB โดยตรง (~5ms, ไม่แตะ ODL)
  Tier 2 (Fresh) — GET /interfaces/discover  → ไป ODL จริง แล้ว sync ลง DB

Frontend ควรใช้ /cached เป็น default และเรียก /discover เฉพาะตอน:
  - หน้า interface แสดงผลครั้งแรกหลัง mount (เพื่อ sync ข้อมูลล่าสุด)
  - หลังจาก push config เสร็จ (เพื่อ refresh สถานะ)
  - User กดปุ่ม "Refresh" เอง
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
    "/devices/{node_id}/interfaces",
    summary="Get interfaces from DB",
    description=(
        "ดึง interface list จาก Database โดยตรง ไม่ยิง ODL เลย (~5ms). "
        "ใช้เป็น default สำหรับแสดงหน้า interface list. "
        "ข้อมูลจะเป็นปัจจุบันเท่ากับครั้งล่าสุดที่เรียก /interfaces/discover"
    ),
)
async def get_interfaces_from_db(
    node_id: str,
    include_down: bool = Query(True, description="รวม interface ที่ status=DOWN ด้วย"),
):
    """
    📦 Get interface list from Database (no ODL contact).

    ใช้เมื่อ:
    - แสดง interface list สำหรับ dropdown / table ทั่วไป
    - Load หน้าซ้ำๆ (ไม่ต้องไปรบกวน ODL ทุกครั้ง)
    - Device ไม่ได้ mounted อยู่ (ดูข้อมูลเก่าได้)

    ไม่เหมาะเมื่อ:
    - ต้องการข้อมูล real-time จาก device → ใช้ /interfaces/discover แทน
    """
    try:
        # 1. Resolve node_id → device_id
        device = await device_service.get(node_id)
        if not device:
            raise HTTPException(
                status_code=404,
                detail={"error": "DEVICE_NOT_FOUND", "message": f"Device '{node_id}' not found"},
            )

        # 2. Read from DB directly
        prisma = get_prisma_client()
        db_device_id = device.device_id

        where_clause = {"device_id": db_device_id}
        if not include_down:
            where_clause["status"] = "UP"

        db_interfaces = await prisma.interface.find_many(
            where=where_clause,
            order={"name": "asc"},
        )

        if not db_interfaces:
            return {
                "success": True,
                "node_id": node_id,
                "source": "database",
                "count": 0,
                "interfaces": [],
                "message": (
                    "No interfaces found in DB. "
                    "Call GET /interfaces/discover first to populate."
                ),
            }

        # 3. Format response (same shape as /discover for frontend consistency)
        interfaces = []
        for intf in db_interfaces:
            ipv4 = None
            if intf.ip_address and intf.subnet_mask:
                ipv4 = f"{intf.ip_address} ({intf.subnet_mask})"
            elif intf.ip_address:
                ipv4 = intf.ip_address

            interfaces.append({
                "name": intf.name,
                "type": intf.type or "OTHER",
                "number": str(intf.port_number) if intf.port_number is not None else "",
                "description": intf.description or "",
                "admin_status": "up" if intf.status == "UP" else "down",
                "ipv4": ipv4,
                "ipv4_address": intf.ip_address,
                "subnet_mask": intf.subnet_mask,
                "mac_address": intf.mac_address,
                "tp_id": intf.tp_id,
                # Oper fields not stored in DB — use /discover for live data
                "oper_status": None,
                "speed": None,
                "duplex": None,
            })

        return {
            "success": True,
            "node_id": node_id,
            "source": "database",
            "count": len(interfaces),
            "interfaces": interfaces,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to read interfaces from DB for {node_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": "DB_READ_FAILED", "message": str(e)},
        )



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
        # Bulk upsert interfaces — Prisma ORM (safe enum handling)
        # เดิม: find_first × N + update/create × N = 2N queries
        # ใหม่: create_many (skip duplicates) + update_many = 2 queries เสมอ
        # ==========================================
        prisma = get_prisma_client()
        try:
            db_device_id = device.device_id
            rows_to_upsert = []

            for intf in interfaces:
                intf_name = intf.get("name")
                if not intf_name:
                    continue

                raw_type = intf.get("type", "").lower()
                if "loopback" in raw_type:
                    intf_type = "LOOPBACK"
                elif "vlan" in raw_type:
                    intf_type = "VLAN"
                elif "tunnel" in raw_type:
                    intf_type = "TUNNEL"
                elif "virtual" in raw_type:
                    intf_type = "VIRTUAL"
                elif any(k in raw_type for k in ("ethernet", "fast", "gigabit", "port-channel")):
                    intf_type = "PHYSICAL"
                else:
                    intf_type = "OTHER"

                port_num_str = intf.get("number")
                port_number = int(port_num_str) if port_num_str and str(port_num_str).isdigit() else None

                rows_to_upsert.append({
                    "device_id": db_device_id,
                    "name": intf_name,
                    "tp_id": f"{node_id}:{intf_name}",
                    "description": intf.get("description") or "",
                    "status": "UP" if intf.get("admin_status") == "up" else "DOWN",
                    "ip_address": intf.get("ipv4_address"),
                    "subnet_mask": intf.get("subnet_mask"),
                    "mac_address": intf.get("mac_address"),
                    "port_number": port_number,
                    "type": intf_type,
                })

            if rows_to_upsert:
                # Step 1: Insert new rows only (skip existing device_id+name combos)
                # create_many with skip_duplicates=True uses ON CONFLICT DO NOTHING
                await prisma.interface.create_many(
                    data=rows_to_upsert,
                    skip_duplicates=True,
                )

                # Step 2: Update existing rows (those that were skipped above)
                for row in rows_to_upsert:
                    await prisma.interface.update_many(
                        where={
                            "device_id": db_device_id,
                            "name": row["name"],
                        },
                        data={
                            "tp_id": row["tp_id"],
                            "description": row["description"],
                            "status": row["status"],
                            "ip_address": row["ip_address"],
                            "subnet_mask": row["subnet_mask"],
                            "mac_address": row["mac_address"],
                            "port_number": row["port_number"],
                            "type": row["type"],
                        },
                    )

                logger.info(
                    f"Upserted {len(rows_to_upsert)} interfaces "
                    f"for '{node_id}' (create_many + update_many)"
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
