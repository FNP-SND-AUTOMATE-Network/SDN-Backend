"""
CSRF Protection Utilities
ระบบป้องกัน Cross-Site Request Forgery สำหรับ Cookie-based Authentication

Pattern: Double-Submit Cookie
- Backend sets `csrf_token` cookie (readable by JS, SameSite=Strict)
- Frontend reads the cookie and sends it as `X-CSRF-Token` header
- Backend compares the header value vs. the cookie value
- Mismatch = rejected (attacker's page cannot read the victim's cookie)

Exempt paths (bypass CSRF check):
- GET / HEAD / OPTIONS (safe methods)
- /auth/* (login/register — no session yet)
- /api/v1/zabbix/webhook (uses own Bearer token auth)
- /health
- WebSocket upgrade requests
"""

import secrets
import hmac
from typing import Optional


# ---------------------------------------------------------------------------
# Token Generation
# ---------------------------------------------------------------------------

def generate_csrf_token() -> str:
    """
    Generate a cryptographically secure CSRF token.
    Returns URL-safe base64 string (256 bits of entropy).
    """
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Token Validation
# ---------------------------------------------------------------------------

def validate_csrf_token(cookie_value: Optional[str], header_value: Optional[str]) -> bool:
    """
    Compare the CSRF token from the cookie and the X-CSRF-Token header.

    Uses hmac.compare_digest to prevent timing-based side-channel attacks.

    Args:
        cookie_value:  Value of the `csrf_token` cookie sent by the browser.
        header_value:  Value of the `X-CSRF-Token` request header.

    Returns:
        True if both values are non-empty and match, False otherwise.
    """
    if not cookie_value or not header_value:
        return False

    # Encode to bytes for hmac comparison
    try:
        return hmac.compare_digest(
            cookie_value.encode("utf-8"),
            header_value.encode("utf-8"),
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Exempt Path Checker
# ---------------------------------------------------------------------------

# Paths that are exempt from CSRF enforcement
_CSRF_EXEMPT_PREFIXES = (
    "/auth/",           # Login, register, OTP — no cookie yet
    "/api/v1/zabbix/",  # Zabbix webhook — uses its own Bearer token
    "/health",          # Health check — read-only, no auth
    "/ws",              # WebSocket upgrades
    "/docs",            # Swagger UI
    "/openapi.json",    # OpenAPI schema
    "/redoc",           # ReDoc UI
)

# Exact paths also exempt
_CSRF_EXEMPT_EXACT = {
    "/auth/login",
    "/auth/register",
    "/auth/verify-otp",
    "/auth/resend-otp",
    "/auth/forgot-password",
    "/auth/reset-password",
    "/auth/mfa-verify-totp-login",
    "/auth/refresh",
}

# Safe HTTP methods (never need CSRF)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def is_csrf_exempt(path: str, method: str) -> bool:
    """
    Determine whether a request is exempt from CSRF validation.

    Args:
        path:    Request URL path (e.g. '/auth/login')
        method:  HTTP method (e.g. 'POST')

    Returns:
        True if the request is exempt from CSRF checking.
    """
    # Safe methods never need CSRF
    if method.upper() in _SAFE_METHODS:
        return True

    # Exact path match
    if path in _CSRF_EXEMPT_EXACT:
        return True

    # Prefix match
    for prefix in _CSRF_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True

    return False
