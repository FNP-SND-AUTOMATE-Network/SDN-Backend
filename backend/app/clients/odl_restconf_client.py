"""
OpenDaylight RESTCONF Client
ตัวเชื่อมต่อ HTTP หลักสำหรับสื่อสารกับ ODL Controller ผ่าน RESTCONF (RFC-8040)

หน้าที่หลัก:
- ส่ง HTTP Request (GET/PUT/POST/DELETE) ไปยัง ODL RESTCONF API
- ใช้ Persistent Connection Pool เพื่อประสิทธิภาพ (TCP Reuse)
- รองรับ Retry พร้อม Exponential Backoff
- แปลง Error จาก ODL ให้เป็นข้อความที่อ่านเข้าใจง่าย (parse_odl_error)
"""

import httpx
import asyncio
from typing import Any, Dict, Optional
from app.core.config import settings
from app.core.errors import OdlRequestError
from app.core.logging import logger
from app.schemas.request_spec import RequestSpec


class OdlRestconfClient:
    """
    OpenDaylight RESTCONF Client using RFC-8040 format

    RFC-8040 path mapping:
    - config/operational → /rests/data/
    - operations → /rests/operations/

    Uses a **shared** persistent httpx.AsyncClient for connection pooling
    and TCP reuse across all ODL requests.

    Usage:
        from app.clients.odl_restconf_client import odl_restconf_client
        response = await odl_restconf_client.send(spec)
    """

    # ── Class-level shared HTTP client ──────────────────────
    _shared_client: Optional[httpx.AsyncClient] = None
    _shared_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self):
        self.base_url = settings.ODL_BASE_URL.rstrip("/")
        self.auth = (settings.ODL_USERNAME, settings.ODL_PASSWORD)
        self.timeout = settings.ODL_TIMEOUT_SEC
        self.retry = settings.ODL_RETRY

    @classmethod
    async def _get_client(cls) -> httpx.AsyncClient:
        """
        ดึงหรือสร้าง Shared HTTP Client (ใช้ Connection Pool ร่วมกันทั้งระบบ)
        - ใช้ Double-Check Locking ป้องกันการสร้าง Client ซ้ำใน Concurrent Request
        - รองรับ TCP Connection สูงสุด 20 connections, Keep-alive 10
        """
        if cls._shared_client is None or cls._shared_client.is_closed:
            async with cls._shared_lock:
                # Double-check after acquiring lock
                if cls._shared_client is None or cls._shared_client.is_closed:
                    cls._shared_client = httpx.AsyncClient(
                        timeout=settings.ODL_TIMEOUT_SEC,
                        limits=httpx.Limits(
                            max_connections=20,
                            max_keepalive_connections=10,
                        ),
                    )
                    logger.info("[ODL-HTTP] Shared persistent client created")
        return cls._shared_client

    @classmethod
    async def close(cls):
        """ปิด Shared HTTP Client อย่างสมบูรณ์ — เรียกตอน App Shutdown"""
        if cls._shared_client and not cls._shared_client.is_closed:
            await cls._shared_client.close()
            cls._shared_client = None
            logger.info("[ODL-HTTP] Shared persistent client closed")

    def _full_url(self, spec: RequestSpec) -> str:
        """
        สร้าง URL เต็มรูปแบบตาม RFC-8040
        - config/operational → /rests/data/
        - operations (RPC) → /rests/operations/
        """
        if spec.datastore == "operations":
            return f"{self.base_url}/rests/operations{spec.path}"
        else:
            # RFC-8040: both config and operational use /rests/data/
            return f"{self.base_url}/rests/data{spec.path}"

    async def send(self, spec: RequestSpec) -> Dict[str, Any]:
        """
        ส่งคำสั่ง RESTCONF ไปยัง ODL Controller
        - รับ RequestSpec (ระบุ method, path, datastore, payload)
        - Retry ตามค่า ODL_RETRY พร้อม Exponential Backoff
        - แปลง Error จาก ODL เป็นข้อความที่อ่านเข้าใจง่ายผ่าน parse_odl_error
        - คืนค่า JSON dict ถ้าสำเร็จ หรือ raise OdlRequestError
        """
        url = self._full_url(spec)
        headers = dict(spec.headers) if spec.headers else {}

        # Log the request for debugging
        logger.info(f"ODL Request: {spec.method} {url}")
        if spec.payload:
            logger.debug(f"Payload: {spec.payload}")

        last_error: Optional[Exception] = None
        client = await self._get_client()

        for attempt in range(self.retry + 1):
            try:
                if spec.payload is not None:
                    resp = await client.request(
                        method=spec.method,
                        url=url,
                        auth=self.auth,
                        headers=headers,
                        json=spec.payload,
                    )
                else:
                    resp = await client.request(
                        method=spec.method,
                        url=url,
                        auth=self.auth,
                        headers=headers,
                    )

                logger.debug(f"ODL Response: {resp.status_code}")

                if 200 <= resp.status_code < 300:
                    if resp.text:
                        try:
                            return resp.json()
                        except Exception:
                            return {"raw": resp.text}
                    return {"ok": True}

                from app.utils.odl_error_parser import parse_odl_error
                friendly_message = parse_odl_error(resp.status_code, resp.text)

                raise OdlRequestError(
                    status_code=resp.status_code,
                    message=friendly_message,
                    details={"url": url, "status": resp.status_code, "body": resp.text},
                )

            except OdlRequestError:
                raise  # Don't retry application-level errors (4xx, 5xx from ODL)

            except Exception as e:
                last_error = e
                logger.debug(f"ODL attempt {attempt+1} failed: {e}")

                # Exponential backoff before next retry (1s, 2s, 4s, ...)
                if attempt < self.retry:
                    backoff = min(2 ** attempt, 8)
                    logger.debug(f"ODL retry backoff: {backoff}s before attempt {attempt+2}")
                    await asyncio.sleep(backoff)

        if isinstance(last_error, OdlRequestError):
            raise last_error
        raise OdlRequestError(502, "ODL failed after retries", details=str(last_error))


# ── Module-level singleton ──────────────────────────────────
# All services should import and use this instance:
#   from app.clients.odl_restconf_client import odl_restconf_client
odl_restconf_client = OdlRestconfClient()
