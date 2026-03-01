from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.api import health, auth, audit, users, device_credentials, local_sites, tags, operating_systems, policies, backups, configuration_templates, device_networks, nbi, interfaces, odl_probe, debug_env, ipam, device_backups
from app.database import set_prisma_client
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.odl_sync_service import OdlSyncService
from app.core.logging import logger
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to database
    from prisma import Prisma
    prisma_client = Prisma()
    await prisma_client.connect()
    set_prisma_client(prisma_client)

    # Startup: Initialize background sync scheduler
    scheduler = AsyncIOScheduler()
    sync_service = OdlSyncService()
    
    # Run device sync every 1 minute
    scheduler.add_job(
        sync_service.sync_devices_from_odl, 
        'interval', 
        minutes=1,
        id='sync_odl_devices',
        replace_existing=True
    )
    
    # Run topology sync every 5 minutes
    from app.services.topology_sync import sync_odl_topology_to_db
    scheduler.add_job(
        sync_odl_topology_to_db,
        'interval',
        minutes=5,
        id='sync_odl_topology',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Background ODL sync scheduler started.")

    yield
    # Shutdown: Stop scheduler and disconnect database
    scheduler.shutdown()
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
