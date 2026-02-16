"""
NBI Helper Functions
"""
from typing import Dict, Any, Optional
from fastapi.responses import JSONResponse
from .models import ErrorCode


def create_error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    """สร้าง error response แบบ consistent"""
    content = {
        "success": False,
        "code": code.value,
        "message": message,
        "data": details
    }
    return JSONResponse(status_code=status_code, content=content)


def create_success_response(
    message: str,
    data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """สร้าง success response แบบ consistent"""
    return {
        "success": True,
        "code": ErrorCode.SUCCESS.value,
        "message": message,
        "data": data
    }
