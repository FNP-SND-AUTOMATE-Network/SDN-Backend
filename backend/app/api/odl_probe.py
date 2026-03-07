from fastapi import APIRouter
import httpx
from app.core.config import settings

router = APIRouter(prefix="/api/v1/debug", tags=["DEBUG"])

@router.get("/odl")
async def probe_odl():
    """
    เช็คว่า backend ยิงไปหา ODL ได้ไหม (RESTCONF up + auth ok)
    RFC-8040 RESTCONF uses /rests/data as base path for data operations
    """
    # ดึง config จาก .env โดยตรง
    url = settings.ODL_BASE_URL.rstrip("/") + "/rests/data/network-topology:network-topology"
    auth = (settings.ODL_USERNAME, settings.ODL_PASSWORD)
    headers = {"Accept": "application/yang-data+json"}

    try:
        async with httpx.AsyncClient(timeout=settings.ODL_TIMEOUT_SEC) as client:
            resp = await client.get(url, auth=auth, headers=headers)

        # 200 = OK with data, 204 = OK no content, 404 = path not found but RESTCONF works
        return {
            "ok": resp.status_code in (200, 204),
            "status": resp.status_code,
            "url": url,
            "message": "ODL RESTCONF (RFC-8040) is reachable" if resp.status_code in (200, 204) else f"ODL returned {resp.status_code}"
        }
    except Exception as e:
        return {
            "ok": False,
            "status": 0,
            "url": url,
            "message": f"Connection failed: {str(e)}"
        }
