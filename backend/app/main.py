from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.api import health, auth, audit, users, device_credentials, local_sites, tags, operating_systems, policies, backups, configuration_templates, device_networks, nbi, interfaces, odl_probe, debug_env, ipam, device_backups, deployments
from app.database import set_prisma_client
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.odl_sync_service import OdlSyncService
from app.core.config import settings as app_settings
from app.core.logging import logger

# Lock to prevent concurrent sync runs
_sync_device_lock = asyncio.Lock()
_sync_topology_lock = asyncio.Lock()


async def _safe_sync_devices():
    """Background job: sync device status จาก ODL (with lock)"""
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
    """Background job: sync topology จาก ODL (with lock)"""
    if _sync_topology_lock.locked():
        logger.debug("[BG-Sync] Topology sync skipped — previous run still in progress")
        return
    async with _sync_topology_lock:
        try:
            from app.services.topology_sync import sync_odl_topology_to_db
            await sync_odl_topology_to_db()
            logger.info("[BG-Sync] Topology sync completed")
        except Exception as e:
            logger.error(f"[BG-Sync] Topology sync failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to database
    from prisma import Prisma
    prisma_client = Prisma()
    await prisma_client.connect()
    set_prisma_client(prisma_client)

    scheduler = None

    if app_settings.SYNC_ENABLED:
        # Startup: Initialize background sync scheduler
        scheduler = AsyncIOScheduler()

        device_interval = app_settings.SYNC_DEVICE_INTERVAL_SEC
        topo_interval = app_settings.SYNC_TOPOLOGY_INTERVAL_SEC

        # Device status sync (NETCONF + OpenFlow)
        scheduler.add_job(
            _safe_sync_devices,
            'interval',
            seconds=device_interval,
            id='sync_odl_devices',
            replace_existing=True
        )

        # Topology sync
        scheduler.add_job(
            _safe_sync_topology,
            'interval',
            seconds=topo_interval,
            id='sync_odl_topology',
            replace_existing=True
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
    await prisma_client.disconnect()

app = FastAPI(
    title="Endpoint API FNP.",
    version="1.0.0",
    description="Authentication and Management API for FNP.",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # React frontend (development)
        "http://127.0.0.1:3000",  # Alternative localhost format
        # Add production domains here when deploying
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
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
app.include_router(odl_probe.router)
app.include_router(debug_env.router)
app.include_router(device_backups.router)
app.include_router(deployments.router)
