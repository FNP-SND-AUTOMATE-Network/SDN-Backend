"""
Custom Error Definitions
รวม Exception Classes ที่ใช้เฉพาะในระบบ SDN

หน้าที่หลัก:
- กำหนด HTTP Exception ที่มี status code และ message เฉพาะสำหรับแต่ละสถานการณ์
- ทำให้ Error Handling เป็นมาตรฐานเดียวกันทั้งระบบ
- ใช้ใน Service Layer เพื่อ raise error กลับไปยัง API Layer
"""

from fastapi import HTTPException

class DeviceNotFound(HTTPException):
    """ไม่พบอุปกรณ์ในระบบ — ใช้เมื่อค้นหา device_id แล้วไม่เจอใน DB (HTTP 404)"""
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
    """Intent ไม่รองรับ — ใช้เมื่อ Intent ที่ร้องขอไม่มีใน Registry หรือ OS ไม่รองรับ (HTTP 400)"""
    def __init__(self, message: str, os_type: str = None):
        if os_type:
            detail = f"Intent '{message}' is not supported in OS '{os_type}'"
        else:
            if " " not in message:
                detail = f"Unsupported intent: {message}"
            else:
                detail = message
        super().__init__(status_code=400, detail=detail)

class DriverBuildError(HTTPException):
    """สร้าง Driver ไม่สำเร็จ — ใช้เมื่อ DriverFactory ไม่สามารถสร้าง Driver สำหรับ Vendor/OS ที่ระบุได้ (HTTP 400)"""
    def __init__(self, msg: str):
        super().__init__(status_code=400, detail=f"Driver build error: {msg}")

class OdlRequestError(HTTPException):
    """ODL RESTCONF Request ล้มเหลว — ใช้เมื่อการส่งคำสั่งไปยัง OpenDaylight Controller ผิดพลาด (HTTP status ตาม ODL)"""
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
