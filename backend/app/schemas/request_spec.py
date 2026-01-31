from pydantic import BaseModel
from typing import Any, Dict, Optional, Literal

Datastore = Literal["config", "operational", "operations"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

class RequestSpec(BaseModel):
    method: HttpMethod
    datastore: Datastore
    path: str  # MUST start with "/network-topology:..."
    payload: Optional[Dict[str, Any]] = None
    headers: Dict[str, str] = {}
    intent: str
    driver: str
