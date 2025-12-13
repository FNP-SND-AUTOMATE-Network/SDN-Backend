from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.api import health, auth, audit, users, device_credentials, local_sites, tags, operating_systems, policies, backups, configuration_templates, device_networks, interfaces
from app.database import set_prisma_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to database
    from prisma import Prisma
    prisma_client = Prisma()
    await prisma_client.connect()
    set_prisma_client(prisma_client)
    yield
    # Shutdown: Disconnect from database
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
