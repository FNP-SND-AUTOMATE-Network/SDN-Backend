from fastapi import HTTPException

class DeviceNotFound(HTTPException):
    def __init__(self, device_id: str):
        super().__init__(status_code=404, detail=f"Device not found: {device_id}")

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
