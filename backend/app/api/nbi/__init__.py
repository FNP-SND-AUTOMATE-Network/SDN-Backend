"""
NBI (Northbound Interface) API
Intent-Based API สำหรับ Network Operations

Flow:
1. สร้าง Device ใน DB (พร้อม node_id และ NETCONF credentials)
2. Mount Device ใน ODL ผ่าน API
3. Check/Sync Connection Status
4. ใช้งาน Intent API

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

Structure:
- models.py     - Error codes, Request/Response models
- helpers.py    - Helper functions
- intents.py    - Intent execution endpoints
- devices.py    - Device listing/detail endpoints
- odl.py        - ODL sync endpoints
- mount.py      - Mount/Unmount endpoints
- health.py     - Health check endpoint
"""
from fastapi import APIRouter

# Import sub-routers
from .intents import router as intents_router
from .devices import router as devices_router
from .odl import router as odl_router
from .mount import router as mount_router
from .health import router as health_router
from .discovery import router as discovery_router
from .topology import router as topology_router

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

# Create main router
router = APIRouter(prefix="/api/v1/nbi", tags=["NBI"])

# Include all sub-routers
router.include_router(intents_router)
router.include_router(devices_router)
router.include_router(odl_router)
router.include_router(mount_router)
router.include_router(health_router)
router.include_router(discovery_router)
router.include_router(topology_router)
