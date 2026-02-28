import httpx
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
    """
    
    def __init__(self):
        # Initial values (will be updated dynamically on each request)
        self.base_url = settings.ODL_BASE_URL.rstrip("/")
        self.auth = (settings.ODL_USERNAME, settings.ODL_PASSWORD)
        self.timeout = settings.ODL_TIMEOUT_SEC
        self.retry = settings.ODL_RETRY

    def _full_url(self, spec: RequestSpec) -> str:
        """
        Build RFC-8040 compliant RESTCONF URL
        
        RFC-8040 uses:
        - /rests/data/ for both config and operational data
        - /rests/operations/ for RPC operations
        """
        if spec.datastore == "operations":
            return f"{self.base_url}/rests/operations{spec.path}"
        else:
            # RFC-8040: both config and operational use /rests/data/
            return f"{self.base_url}/rests/data{spec.path}"

    async def send(self, spec: RequestSpec) -> Dict[str, Any]:
        url = self._full_url(spec)
        headers = dict(spec.headers) if spec.headers else {}
        
        # Log the request for debugging
        logger.info(f"ODL Request: {spec.method} {url}")
        if spec.payload:
            logger.debug(f"Payload: {spec.payload}")

        last_error: Optional[Exception] = None

        for attempt in range(self.retry + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    # Only send json body if payload exists
                    if spec.payload is not None:
                        resp = await client.request(
                            method=spec.method,
                            url=url,
                            auth=self.auth,
                            headers=headers,
                            json=spec.payload
                        )
                    else:
                        resp = await client.request(
                            method=spec.method,
                            url=url,
                            auth=self.auth,
                            headers=headers
                        )

                logger.info(f"ODL Response: {resp.status_code}")

                if 200 <= resp.status_code < 300:
                    if resp.text:
                        try:
                            return resp.json()
                        except Exception:
                            return {"raw": resp.text}
                    return {"ok": True}

                raise OdlRequestError(
                    status_code=resp.status_code,
                    message="ODL RESTCONF request failed",
                    details={"url": url, "status": resp.status_code, "body": resp.text}
                )

            except Exception as e:
                last_error = e
                logger.info(f"ODL attempt {attempt+1} failed: {e}")

        if isinstance(last_error, OdlRequestError):
            raise last_error
        raise OdlRequestError(502, "ODL failed after retries", details=str(last_error))
