"""
Request Helper Utilities
Shared utility functions for extracting request metadata.

Replaces copy-pasted IP extraction logic across 8+ API handlers.
"""

import re
from fastapi import Request


# ── Path parameter validation ─────────────────────────────────────────────────
# Allow alphanumeric, hyphens, underscores, dots, colons (for ODL node IDs like "openflow:1")
_SAFE_PATH_RE = re.compile(r"^[a-zA-Z0-9_\-\.\:]+$")
_MAX_PATH_PARAM_LENGTH = 256


def validate_path_param(value: str, param_name: str = "parameter") -> str:
    """
    Validate a path parameter against injection attacks.

    Raises ValueError if the value contains unsafe characters.
    Used for node_id, flow_id, device_id etc. that end up in ODL RESTCONF URLs.
    """
    if not value or not value.strip():
        raise ValueError(f"{param_name} cannot be empty")

    if len(value) > _MAX_PATH_PARAM_LENGTH:
        raise ValueError(f"{param_name} exceeds maximum length of {_MAX_PATH_PARAM_LENGTH}")

    if not _SAFE_PATH_RE.match(value):
        raise ValueError(
            f"{param_name} contains invalid characters. "
            f"Only alphanumeric, hyphens, underscores, dots, and colons are allowed."
        )

    return value


# ── Client IP extraction ──────────────────────────────────────────────────────

def get_client_ip(request: Request) -> str:
    """
    Extract the real client IP address from a request.

    Checks headers in order:
    1. X-Forwarded-For (first entry — set by reverse proxy)
    2. X-Real-IP (set by Nginx)
    3. request.client.host (direct connection)

    Returns "unknown" if no IP can be determined.
    """
    if "x-forwarded-for" in request.headers:
        # X-Forwarded-For can contain multiple IPs: "client, proxy1, proxy2"
        return request.headers["x-forwarded-for"].split(",")[0].strip()

    if "x-real-ip" in request.headers:
        return request.headers["x-real-ip"]

    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def get_user_agent(request: Request) -> str:
    """Extract user agent from request headers."""
    return request.headers.get("user-agent", "unknown")
