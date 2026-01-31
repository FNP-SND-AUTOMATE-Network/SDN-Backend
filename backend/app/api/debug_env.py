from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/api/v1/debug", tags=["DEBUG"])

@router.get("/env")
def debug_env():
    return {
        "ODL_BASE_URL": settings.ODL_BASE_URL,
        "ODL_USERNAME": settings.ODL_USERNAME,
        "ODL_TIMEOUT_SEC": settings.ODL_TIMEOUT_SEC,
        "ODL_RETRY": settings.ODL_RETRY,
    }
