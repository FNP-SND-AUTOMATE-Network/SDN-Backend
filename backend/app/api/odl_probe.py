from fastapi import APIRouter
import httpx
from app.core.config import settings

router = APIRouter(prefix="/api/v1/debug", tags=["DEBUG"])

@router.get("/odl")
async def probe_odl():
    """
    เช็คว่า backend ยิงไปหา ODL ได้ไหม (RESTCONF up + auth ok)
    """
    url = settings.ODL_BASE_URL.rstrip("/") + "/restconf"
    auth = (settings.ODL_USERNAME, settings.ODL_PASSWORD)

    async with httpx.AsyncClient(timeout=settings.ODL_TIMEOUT_SEC) as client:
        resp = await client.get(url, auth=auth)

    # 204/200 ถือว่า OK
    return {
        "ok": resp.status_code in (200, 204),
        "status": resp.status_code,
        "url": url
    }
