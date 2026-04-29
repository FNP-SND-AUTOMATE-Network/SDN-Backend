"""
Network Interfaces API

รวม endpoint ทั้งหมดที่เกี่ยวกับ Interface ไว้ในที่เดียว:

  ── Read / Delete (DB) ──────────────────────────────────────────────
  GET    /interfaces/                         → list ทั้งหมด (paginated)
  GET    /interfaces/device/{device_id}       → list by device_id
  GET    /interfaces/{interface_id}           → get by ID
  DELETE /interfaces/{interface_id}           → delete stale interface

  ── ODL Sync & Discovery ────────────────────────────────────────────
  GET    /interfaces/odl/{node_id}            → อ่านจาก DB by node_id (~5ms)
  GET    /interfaces/odl/{node_id}/sync       → ODL fetch → DB upsert → DB read-back
  GET    /interfaces/odl/{node_id}/names      → เฉพาะชื่อ interface (dropdown)

หมายเหตุ:
  - Interface data ต้องมาจาก device จริง (ผ่าน ODL sync) เท่านั้น
  - ไม่มี POST (create) / PUT (update) — ข้อมูลต้องตรงกับ device
  - /sync จะยิง ODL จริงทุกครั้ง (force_refresh=True) ไม่ใช้ cache
  - Frontend ควรใช้ /odl/{node_id} เป็น default (อ่านจาก DB เร็ว)
    และเรียก /odl/{node_id}/sync เฉพาะตอน mount ใหม่ / push config / กด Refresh
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, Optional, List
from app.database import get_db, get_prisma_client
from app.api.users import get_current_user, check_engineer_permission
from app.services.interface_service import InterfaceService
from app.services.interface_discovery_service import InterfaceDiscoveryService
from app.services.device_profile_service_db import DeviceProfileService
from app.core.logging import logger
from app.models.interface import (
    InterfaceResponse,
    InterfaceListResponse,
    InterfaceDeleteResponse,
    InterfaceStatus,
    InterfaceType
)
from app.services.phpipam_service import PhpipamService
from prisma import Prisma
import asyncio

router = APIRouter(prefix="/interfaces", tags=["Network Interfaces"])

# ── Service singletons ───────────────────────────────────────────────
discovery_service = InterfaceDiscoveryService()
device_service = DeviceProfileService()

def get_interface_service(db: Prisma = Depends(get_db)) -> InterfaceService:
    return InterfaceService(db)


# =====================================================================
#  Read & Delete Endpoints (DB only, requires auth)
# =====================================================================

@router.get("/", response_model=InterfaceListResponse)
async def get_interfaces(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    device_id: Optional[str] = Query(None, description="Filter by Device ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    interface_type: Optional[str] = Query(None, description="Filter by interface type"),
    search: Optional[str] = Query(None, description="Search by name, label, or description"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    try:
        interfaces, total = await interface_svc.get_interfaces(
            page=page,
            page_size=page_size,
            device_id=device_id,
            status=status,
            interface_type=interface_type,
            search=search
        )

        return InterfaceListResponse(
            total=total,
            page=page,
            page_size=page_size,
            interfaces=interfaces
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching interfaces: {str(e)}"
        )

@router.get("/device/{device_id}", response_model=List[InterfaceResponse])
async def get_interfaces_by_device(
    device_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    try:
        interfaces = await interface_svc.get_interfaces_by_device(device_id)
        return interfaces

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching interfaces by device: {str(e)}"
        )

@router.get("/{interface_id}", response_model=InterfaceResponse)
async def get_interface(
    interface_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    try:
        interface = await interface_svc.get_interface_by_id(interface_id)
        
        if not interface:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interface not found"
            )
        
        return interface

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching interface: {str(e)}"
        )

@router.delete("/{interface_id}", response_model=InterfaceDeleteResponse)
async def delete_interface(
    interface_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete an interface"
            )

        success = await interface_svc.delete_interface(interface_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete interface"
            )

        return InterfaceDeleteResponse(
            message="Interface deleted successfully"
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting interface: {str(e)}"
        )


# =====================================================================
#  ODL Sync & Discovery Endpoints (requires auth — used by frontend)
# =====================================================================

@router.get(
    "/odl/{node_id}",
    summary="Get interfaces from DB by node_id",
    description=(
        "ดึง interface list จาก Database โดยตรง ไม่ยิง ODL เลย (~5ms). "
        "ใช้เป็น default สำหรับแสดงหน้า interface list. "
        "ข้อมูลจะเป็นปัจจุบันเท่ากับครั้งล่าสุดที่เรียก /interfaces/odl/{node_id}/sync"
    ),
)
async def get_interfaces_from_db(
    node_id: str,
    include_down: bool = Query(True, description="รวม interface ที่ status=DOWN ด้วย"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    📦 Get interface list from Database (no ODL contact).

    ใช้เมื่อ:
    - แสดง interface list สำหรับ dropdown / table ทั่วไป
    - Load หน้าซ้ำๆ (ไม่ต้องไปรบกวน ODL ทุกครั้ง)
    - Device ไม่ได้ mounted อยู่ (ดูข้อมูลเก่าได้)

    ไม่เหมาะเมื่อ:
    - ต้องการข้อมูล real-time จาก device → ใช้ /interfaces/odl/{node_id}/sync แทน
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
                    "Call GET /interfaces/odl/{node_id}/sync first to populate."
                ),
            }

        # 3. Format response
        result_interfaces = []
        for intf in db_interfaces:
            ipv4 = None
            if intf.ip_address and intf.subnet_mask:
                ipv4 = f"{intf.ip_address} ({intf.subnet_mask})"
            elif intf.ip_address:
                ipv4 = intf.ip_address

            result_interfaces.append({
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
                "speed": intf.speed,
                "duplex": intf.duplex,
                "mtu": intf.mtu,
                "oper_status": None,
                "phpipam_address_id": intf.phpipam_address_id,
            })

        return {
            "success": True,
            "node_id": node_id,
            "source": "database",
            "count": len(result_interfaces),
            "interfaces": result_interfaces,
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
    "/odl/{node_id}/sync",
    summary="Sync interfaces from device (synchronous)",
    description=(
        "ไปดึง interface list จาก ODL จริง → sync ลง DB → อ่านกลับจาก DB แล้ว return. "
        "Response เป็น DB state เสมอ (source='database') จึงรับประกันว่า "
        "ข้อมูลที่ frontend เห็นตรงกับ DB 100%."
    ),
)
async def sync_interfaces(
    node_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    🔄 Synchronous interface sync: ODL → DB → read-back → return.

    Flow:
      1. Fetch interfaces จาก ODL (config + oper merged)
      2. Upsert ลง DB (hard error ถ้า fail)
      3. Read-back จาก DB เป็น response

    ใช้เมื่อ:
      - หลัง mount device ครั้งแรก (populate interfaces)
      - หลัง push config (refresh สถานะ)
      - User กดปุ่ม "Refresh"

    Returns:
      - source: "database" (อ่านกลับจาก DB เสมอ)
      - synced_count: จำนวน interface ที่ sync ลง DB
      - count: จำนวน interface ที่ return (จาก DB)
    """
    try:
        # ── Step 1: Resolve device ────────────────────────────────────────
        device = await device_service.get(node_id)
        if not device:
            raise HTTPException(
                status_code=404,
                detail={"error": "DEVICE_NOT_FOUND", "message": f"Device '{node_id}' not found"},
            )

        vendor = device.os_type or device.vendor or "cisco"
        db_device_id = device.device_id

        # ── Step 2: Fetch from ODL ────────────────────────────────────────
        interfaces = await discovery_service.discover(
            node_id=device.node_id,
            vendor=vendor,
            force_refresh=True,  # sync = ยิง ODL จริงเสมอ
        )

        # ── Step 3: Upsert to DB (hard error if fails) ───────────────────
        prisma = get_prisma_client()
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

            # Parse speed (convert to int Mbps if possible)
            raw_speed = intf.get("speed")
            speed_mbps = None
            if raw_speed is not None:
                try:
                    speed_int = int(raw_speed)
                    speed_mbps = speed_int // 1_000_000 if speed_int > 1_000_000 else speed_int
                except (ValueError, TypeError):
                    pass

            raw_mtu = intf.get("mtu")
            mtu_val = int(raw_mtu) if raw_mtu is not None else None

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
                "speed": speed_mbps,
                "duplex": intf.get("duplex"),
                "mtu": mtu_val,
            })

        synced_count = 0
        if rows_to_upsert:
            try:
                # Step 3a: Insert new rows (skip existing device_id+name combos)
                await prisma.interface.create_many(
                    data=rows_to_upsert,
                    skip_duplicates=True,
                )

                # Step 3b: Update existing rows
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
                            "speed": row["speed"],
                            "duplex": row["duplex"],
                            "mtu": row["mtu"],
                        },
                    )

                synced_count = len(rows_to_upsert)
                logger.info(
                    f"Synced {synced_count} interfaces "
                    f"for '{node_id}' to DB (create_many + update_many)"
                )
            except Exception as db_e:
                import traceback
                traceback.print_exc()
                logger.error(f"Failed to sync interfaces to DB for {node_id}: {db_e}")
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "DB_SYNC_FAILED",
                        "message": (
                            f"Fetched {len(interfaces)} interfaces from ODL "
                            f"but failed to write to DB: {db_e}"
                        ),
                    },
                )

        # ── Step 3c: IPAM auto-book discovered IPs ────────────────────────
        ipam_notifications = []
        phpipam_svc = PhpipamService()

        if phpipam_svc.enabled and rows_to_upsert:
            # Batch IPAM booking with asyncio.gather + semaphore (Finding #11)
            semaphore = asyncio.Semaphore(5)  # limit concurrent IPAM calls

            async def _book_one(row: dict) -> dict | None:
                ip_addr = row.get("ip_address")
                if not ip_addr:
                    return None
                async with semaphore:
                    try:
                        result = await phpipam_svc.book_ip(
                            ip_address=ip_addr,
                            hostname=f"{node_id}-{row['name']}",
                            mac_address=row.get("mac_address"),
                            purpose="Interface IP"
                        )
                        if result.get("success") and result.get("phpipam_address_id"):
                            await prisma.interface.update_many(
                                where={
                                    "device_id": db_device_id,
                                    "name": row["name"],
                                },
                                data={
                                    "phpipam_address_id": result["phpipam_address_id"]
                                },
                            )
                        return {
                            "interface": row["name"],
                            "ip_address": ip_addr,
                            "code": result.get("code"),
                            "phpipam_address_id": result.get("phpipam_address_id"),
                            "message": result.get("error_message") or result.get("code"),
                        }
                    except Exception as ipam_e:
                        logger.warning(f"IPAM auto-book failed for {ip_addr}: {ipam_e}")
                        return {
                            "interface": row["name"],
                            "ip_address": ip_addr,
                            "code": "IPAM_ERROR",
                            "phpipam_address_id": None,
                            "message": str(ipam_e),
                        }

            results = await asyncio.gather(
                *[_book_one(row) for row in rows_to_upsert],
                return_exceptions=True
            )
            ipam_notifications = [r for r in results if r is not None and not isinstance(r, Exception)]

        # ── Step 4: Read-back from DB (source of truth) ──────────────────
        db_interfaces = await prisma.interface.find_many(
            where={"device_id": db_device_id},
            order={"name": "asc"},
        )

        result_interfaces = []
        for intf in db_interfaces:
            ipv4 = None
            if intf.ip_address and intf.subnet_mask:
                ipv4 = f"{intf.ip_address} ({intf.subnet_mask})"
            elif intf.ip_address:
                ipv4 = intf.ip_address

            result_interfaces.append({
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
                "speed": intf.speed,
                "duplex": intf.duplex,
                "mtu": intf.mtu,
                "oper_status": None,
                "phpipam_address_id": intf.phpipam_address_id,
            })

        return {
            "success": True,
            "node_id": node_id,
            "vendor": vendor,
            "source": "database",
            "synced_count": synced_count,
            "count": len(result_interfaces),
            "interfaces": result_interfaces,
            "ipam_notifications": ipam_notifications,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Interface sync failed for {node_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail={"error": "SYNC_FAILED", "message": str(e)},
        )


@router.get(
    "/odl/{node_id}/names",
    summary="Get interface name list",
    description="ดึงเฉพาะชื่อ interface สำหรับ dropdown",
)
async def get_interface_names(
    node_id: str,
    force_refresh: bool = Query(False, description="Force refresh cache"),
    current_user: Dict[str, Any] = Depends(get_current_user),
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


