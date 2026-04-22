"""
Main Application Entry Point
จุดเริ่มต้นหลักของแอปพลิเคชัน SDN Backend

หน้าที่หลัก:
- สร้าง FastAPI application instance
- กำหนด Lifespan (Startup/Shutdown) สำหรับเชื่อมต่อ Database, เริ่ม Scheduler
- ลงทะเบียน Background Tasks สำหรับ Sync ข้อมูลจาก ODL อัตโนมัติ
- ตั้งค่า CORS Middleware สำหรับ Frontend
- Include ทุก API Router เข้า app
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from app.api import health, auth, audit, users, device_credentials, local_sites, tags, operating_systems, policies, backups, configuration_templates, device_networks, nbi, interfaces, ipam, device_backups, deployments, chatops, zabbix_webhook, zabbix_dashboard, ws_alerts
from app.database import set_prisma_client
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.odl_sync_service import OdlSyncService
from app.core.config import settings as app_settings
from app.core.logging import logger
from app.core.event_bus import event_bus
from app.core.csrf import is_csrf_exempt, validate_csrf_token

# Lock to prevent concurrent sync runs
_sync_device_lock = asyncio.Lock()
_sync_topology_lock = asyncio.Lock()


async def _safe_sync_devices():
    """
    [Background Task] ซิงค์สถานะอุปกรณ์จาก ODL Controller
    - ใช้ Lock ป้องกันไม่ให้ทำงานซ้อนกัน (ถ้ารอบก่อนยังไม่เสร็จจะข้ามรอบนี้)
    - เรียก OdlSyncService.sync_all_devices() เพื่ออัปเดต status ของทุกอุปกรณ์ใน DB
    - ทำงานเป็น Interval Job ตามค่า SYNC_DEVICE_INTERVAL_SEC
    """
    if _sync_device_lock.locked():
        logger.debug("[BG-Sync] Device sync skipped — previous run still in progress")
        return
    async with _sync_device_lock:
        try:
            sync_service = OdlSyncService()
            result = await sync_service.sync_all_devices()
            total = result["summary"]["total_synced"]
            errors = result["summary"]["total_errors"]
            logger.info(f"[BG-Sync] Device sync completed: {total} synced, {errors} errors")
        except Exception as e:
            logger.error(f"[BG-Sync] Device sync failed: {e}")


async def _safe_sync_topology():
    """
    [Background Task] ซิงค์ข้อมูล Topology (Interface/Link) จาก ODL Controller
    - ใช้ Lock ป้องกันไม่ให้ทำงานซ้อนกัน
    - มี Timeout ป้องกันกรณีที่ sync ใช้เวลานานเกินไป (80% ของ interval)
    - เรียก sync_odl_topology_to_db() เพื่ออัปเดต Interface ทั้งหมดลง DB
    - ทำงานเป็น Interval Job ตามค่า SYNC_TOPOLOGY_INTERVAL_SEC
    """
    if _sync_topology_lock.locked():
        logger.debug("[BG-Sync] Topology sync skipped — previous run still in progress")
        return
    async with _sync_topology_lock:
        try:
            from app.services.topology_sync import sync_odl_topology_to_db
            # Total timeout = 80% of interval เพื่อป้องกัน sync ทำงานยาวกว่า interval
            total_timeout = app_settings.SYNC_TOPOLOGY_INTERVAL_SEC * 0.8
            await asyncio.wait_for(sync_odl_topology_to_db(), timeout=total_timeout)
            logger.info("[BG-Sync] Topology sync completed")
        except asyncio.TimeoutError:
            logger.error(
                f"[BG-Sync] Topology sync TIMEOUT after {app_settings.SYNC_TOPOLOGY_INTERVAL_SEC * 0.8:.0f}s "
                f"— consider increasing SYNC_TOPOLOGY_INTERVAL_SEC"
            )
        except Exception as e:
            logger.error(f"[BG-Sync] Topology sync failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    [Lifespan Manager] จัดการ Startup และ Shutdown ของแอปพลิเคชัน

    Startup:
    1. เชื่อมต่อ Prisma Database Client
    2. เริ่ม Backup Scheduler สำหรับ auto-backup ที่ตั้งค่าไว้
    3. เริ่ม ChatOps Service (ถ้าเปิดใช้งาน) สำหรับส่งแจ้งเตือนไปยัง Slack
    4. เริ่ม Background Sync Scheduler สำหรับซิงค์ Device/Topology จาก ODL

    Shutdown:
    1. หยุด Background Sync Scheduler
    2. หยุด Backup Scheduler
    3. ปิด ODL HTTP Client (Connection Pool)
    4. ตัดการเชื่อมต่อ Database
    """
    # Startup: Connect to database
    from prisma import Prisma
    prisma_client = Prisma()
    await prisma_client.connect()
    set_prisma_client(prisma_client)

    # ── Scheduled Backups ──
    from app.core.scheduler import scheduler_manager
    scheduler_manager.start()
    try:
        profiles = await prisma_client.backup.find_many(
            where={
                "auto_backup": True,
                "status": {"not": "PAUSED"},
                "schedule_type": {"not": "NONE"},
                "cron_expression": {"not": None}
            }
        )
        for profile in profiles:
            if profile.cron_expression:
                try:
                    scheduler_manager.add_or_update_backup_job(
                        backup_id=profile.id,
                        cron_expression=profile.cron_expression
                    )
                except Exception as e:
                    logger.error(f"[Scheduler] Failed to register backup job {profile.id} at startup: {e}")
    except Exception as e:
        logger.error(f"[Scheduler] Failed to load backup profiles at startup: {e}")

    # ── ChatOps: Initialize event-driven pipeline ──
    if app_settings.CHATOPS_ENABLED:
        from app.services.chatops_service import chatops_service  # noqa: F811
        logger.info(
            f"[ChatOps] Initialized — Slack webhook {'configured' if app_settings.SLACK_WEBHOOK_URL else 'NOT configured'}"
        )
    else:
        logger.info("[ChatOps] DISABLED (CHATOPS_ENABLED=false)")

    scheduler = None

    if app_settings.SYNC_ENABLED:
        # Startup: Initialize background sync scheduler
        scheduler = AsyncIOScheduler()

        device_interval = app_settings.SYNC_DEVICE_INTERVAL_SEC
        topo_interval = app_settings.SYNC_TOPOLOGY_INTERVAL_SEC

        # Device status sync (NETCONF)
        scheduler.add_job(
            _safe_sync_devices,
            'interval',
            seconds=device_interval,
            id='sync_odl_devices',
            replace_existing=True
        )

        # Topology sync (staggered start: offset by half device_interval to avoid overlap)
        from datetime import datetime, timedelta
        topo_first_run = datetime.now() + timedelta(seconds=device_interval // 2)
        scheduler.add_job(
            _safe_sync_topology,
            'interval',
            seconds=topo_interval,
            id='sync_odl_topology',
            replace_existing=True,
            next_run_time=topo_first_run
        )

        scheduler.start()
        logger.info(
            f"[BG-Sync] Scheduler started — "
            f"Device sync: every {device_interval}s, "
            f"Topology sync: every {topo_interval}s"
        )
    else:
        logger.info("[BG-Sync] Background sync DISABLED (SYNC_ENABLED=false)")

    yield

    # Shutdown
    if scheduler:
        scheduler.shutdown()
        logger.info("[BG-Sync] Scheduler stopped")
        
    try:
        from app.core.scheduler import scheduler_manager
        scheduler_manager.shutdown()
    except Exception as e:
        logger.error(f"[Shutdown] Backup scheduler cleanup: {e}")

    # Close shared ODL HTTP client (class-level singleton)
    try:
        from app.clients.odl_restconf_client import OdlRestconfClient
        await OdlRestconfClient.close()
    except Exception as e:
        logger.debug(f"[Shutdown] ODL client cleanup: {e}")

    await prisma_client.disconnect()

app = FastAPI(
    title="Endpoint API FNP.",
    version="1.0.0",
    description="Authentication and Management API for FNP.",
    lifespan=lifespan
)


# ── Middleware #1: Security Response Headers ──────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Inject security-related HTTP response headers on every response.

    Headers added:
    - X-Content-Type-Options: nosniff        — prevent MIME-type sniffing
    - X-Frame-Options: DENY                  — block iframe embedding (clickjacking)
    - X-XSS-Protection: 1; mode=block       — enable XSS filter (legacy browsers)
    - Referrer-Policy: strict-origin-when-cross-origin
    - Content-Security-Policy                — restrict resource origins
    - Permissions-Policy                     — disable unused browser features
    - Strict-Transport-Security              — enforce HTTPS (production only)
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            # Swagger UI JS is served from cdn.jsdelivr.net
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            # Swagger UI CSS + Google Fonts
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com; "
            # Swagger UI logo from FastAPI CDN + local data URIs
            "img-src 'self' data: blob: https://fastapi.tiangolo.com; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        # HSTS: only in production where HTTPS is guaranteed
        if app_settings.APP_ENV == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        return response


app.add_middleware(SecurityHeadersMiddleware)


# ── Middleware #2: CSRF Protection ────────────────────────────────────────────
class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Double-Submit Cookie CSRF Protection.

    For every state-changing request (POST/PUT/DELETE/PATCH) that uses a
    cookie-based session, the frontend must send the `X-CSRF-Token` header
    whose value matches the `csrf_token` cookie.

    Exempt:
    - Safe HTTP methods (GET, HEAD, OPTIONS)
    - Auth endpoints (/auth/*) — no cookie yet at login time
    - Zabbix webhook (/api/v1/zabbix/) — uses its own Bearer token
    - Requests authenticated via Bearer token only (no access_token cookie)
      — allows API clients / curl / Postman to work without CSRF
    """

    async def dispatch(self, request: Request, call_next):
        # Skip if CSRF globally disabled (dev convenience, never in prod)
        if not app_settings.CSRF_ENABLED:
            return await call_next(request)

        path = request.url.path
        method = request.method

        # Exempt safe methods and known bypass paths
        if is_csrf_exempt(path, method):
            return await call_next(request)

        # If request is using Bearer token only (no cookie), skip CSRF
        # This lets API clients (curl, Postman, external services) work
        has_cookie_session = bool(request.cookies.get("access_token"))
        has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")
        if has_bearer and not has_cookie_session:
            return await call_next(request)

        # Cookie-authenticated request — enforce CSRF
        csrf_cookie = request.cookies.get("csrf_token")
        csrf_header = request.headers.get("X-CSRF-Token")

        if not validate_csrf_token(csrf_cookie, csrf_header):
            logger.warning(
                f"[CSRF] Rejected {method} {path} — "
                f"cookie={'<set>' if csrf_cookie else '<missing>'}, "
                f"header={'<set>' if csrf_header else '<missing>'}"
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token missing or invalid. "
                              "Include X-CSRF-Token header matching the csrf_token cookie."
                }
            )

        return await call_next(request)


app.add_middleware(CSRFMiddleware)


# ── CORS Configuration ────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # React frontend (development)
        "http://127.0.0.1:3000",  # Alternative localhost format
        # Add production domains here when deploying
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*", "X-CSRF-Token"],
)

# Include routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(audit.router)
app.include_router(users.router)
app.include_router(device_credentials.router)
app.include_router(local_sites.router)
app.include_router(tags.router)
app.include_router(operating_systems.router)
app.include_router(policies.router)
app.include_router(backups.router)
app.include_router(configuration_templates.router)
app.include_router(device_networks.router)
app.include_router(interfaces.router)
app.include_router(ipam.router)
app.include_router(nbi.router)
app.include_router(device_backups.router)
app.include_router(deployments.router)
app.include_router(chatops.router)
app.include_router(zabbix_webhook.router)
app.include_router(zabbix_dashboard.router)
app.include_router(ws_alerts.router)
