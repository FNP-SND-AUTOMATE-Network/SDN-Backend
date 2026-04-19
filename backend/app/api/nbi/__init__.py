"""
NBI (Northbound Interface) API
Intent-Based API สำหรับ Network Operations

Flow:
1. สร้าง Device ใน DB (พร้อม node_id และ NETCONF credentials)
2. Mount Device ใน ODL ผ่าน API
3. Check/Sync Connection Status
4. ใช้งาน Intent API

Swagger Tags:
- NBI — Health Check
- NBI — Devices          : Device listing, detail, capabilities
- NBI — Mount            : Mount / Unmount / Wait-ready / Force-remount
- NBI — ODL Sync         : ODL node listing, device status sync
- NBI — Intents          : Intent execution & discovery
- NBI — Topology         : Topology sync & query
- NBI — OpenFlow Flows   : Flow rule CRUD, templates, sync

Error Codes สำหรับ Frontend:
- 200: Success
- 400: Bad Request (ข้อมูลไม่ครบ/ไม่ถูกต้อง)
- 401: Unauthorized (ยังไม่ได้ login)
- 403: Forbidden (ไม่มีสิทธิ์)
- 404: Not Found (ไม่พบ device/intent)
- 409: Conflict (device already mounted, etc.)
- 422: Validation Error (ข้อมูลไม่ผ่าน validation)
- 502: Bad Gateway (ODL connection failed)
- 503: Service Unavailable (ODL not available)
- 504: Gateway Timeout (ODL timeout)
"""
from fastapi import APIRouter

# Import sub-routers
from .intents import router as intents_router
from .devices import router as devices_router
from .odl import router as odl_router
from .mount import router as mount_router
from .health import router as health_router
# discovery.py ถูกย้ายไป /interfaces/ แล้ว — ดู app/api/interfaces.py
from .topology import router as topology_router
from .flows import router as flows_router

# Re-export models for backward compatibility
from .models import (
    ErrorCode,
    APIResponse,
    MountRequest,
    MountResponse,
    SyncResponse,
    DeviceListResponse,
    DeviceDetailResponse,
    IntentListResponse,
    UpdateNetconfRequest,
)

from .helpers import create_error_response, create_success_response

# Create main router (no default tag — each sub-router has its own)
router = APIRouter(prefix="/api/v1/nbi")

# Include all sub-routers with dedicated Swagger tags
router.include_router(health_router,    tags=["NBI — Health Check"])
router.include_router(devices_router,   tags=["NBI — Devices"])
router.include_router(mount_router,     tags=["NBI — Mount"])
router.include_router(odl_router,       tags=["NBI — ODL Sync"])
router.include_router(intents_router,   tags=["NBI — Intents"])
router.include_router(topology_router,  tags=["NBI — Topology"])
router.include_router(flows_router,     tags=["NBI — OpenFlow Flows"])

