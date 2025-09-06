from fastapi import FastAPI
from app.api import health

app = FastAPI(title="API v1", version="1.0.0")

# Include routers
app.include_router(health.router)