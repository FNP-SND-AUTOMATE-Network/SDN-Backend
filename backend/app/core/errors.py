from fastapi import HTTPException

class DeviceNotFound(HTTPException):
    def __init__(self, device_id: str):
        super().__init__(status_code=404, detail=f"Device not found: {device_id}")

class DeviceNotMounted(HTTPException):
    """Error when device is not mounted or not connected in ODL"""
    def __init__(self, message: str):
        super().__init__(
            status_code=400, 
            detail={
                "code": "DEVICE_NOT_MOUNTED",
                "message": message,
                "suggestion": "Use POST /api/v1/nbi/devices/{node_id}/mount to mount the device first"
            }
        )

class UnsupportedIntent(HTTPException):
    def __init__(self, intent: str):
        super().__init__(status_code=400, detail=f"Unsupported intent: {intent}")

class DriverBuildError(HTTPException):
    def __init__(self, msg: str):
        super().__init__(status_code=400, detail=f"Driver build error: {msg}")

class OdlRequestError(HTTPException):
    def __init__(self, status_code: int, message: str, details=None):
        super().__init__(status_code=status_code, detail={
            "message": message,
            "details": details
        })


class UnsupportedVendor(HTTPException):
    """Error when vendor is not supported by DriverFactory"""
    def __init__(self, message: str):
        super().__init__(
            status_code=400,
            detail={
                "code": "UNSUPPORTED_VENDOR",
                "message": message
            }
        )
