from typing import Optional, Dict, Any
import bcrypt
from app.models.device_credentials import (
    DeviceCredentialsCreate, 
    DeviceCredentialsUpdate, 
    DeviceCredentialsResponse
)


class DeviceCredentialsService:
    """Service สำหรับจัดการ Device Network Credentials"""
    
    def __init__(self, prisma_client):
        self.prisma = prisma_client
    
    def _hash_password(self, password: str) -> str:
        """Hash รหัสผ่านด้วย bcrypt"""
        # ตรวจสอบ byte length เพื่อป้องกัน bcrypt truncation
        password_bytes = password.encode('utf-8')
        if len(password_bytes) > 72:
            raise ValueError(f"รหัสผ่านยาวเกินไป ({len(password_bytes)} bytes) bcrypt รองรับได้สูงสุด 72 bytes")
        
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password_bytes, salt).decode('utf-8')
    
    def _verify_password(self, password: str, hashed: str) -> bool:
        """ตรวจสอบรหัสผ่านกับ hash"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    async def get_device_credentials(self, user_id: str) -> Optional[DeviceCredentialsResponse]:
        """ดึงข้อมูล Device Credentials ของ user"""
        try:
            device_creds = await self.prisma.devicecredentials.find_unique(
                where={"userId": user_id}
            )
            
            if not device_creds:
                return None
            
            return DeviceCredentialsResponse(
                id=device_creds.id,
                user_id=device_creds.userId,
                device_username=device_creds.deviceUsername,
                has_password=bool(device_creds.devicePasswordHash),
                created_at=device_creds.createdAt,
                updated_at=device_creds.updatedAt
            )
            
        except Exception as e:
            print(f"Error getting device credentials: {e}")
            raise e
    
    async def create_device_credentials(self, user_id: str, data: DeviceCredentialsCreate) -> Optional[DeviceCredentialsResponse]:
        """สร้าง Device Credentials ใหม่"""
        try:
            # ตรวจสอบว่า user มี device credentials อยู่แล้วหรือไม่
            existing = await self.prisma.devicecredentials.find_unique(
                where={"userId": user_id}
            )
            
            if existing:
                raise ValueError("ผู้ใช้มี Device Credentials อยู่แล้ว กรุณาใช้การอัปเดตแทน")
            
            # Hash รหัสผ่าน
            password_hash = self._hash_password(data.device_password)
            
            # สร้าง device credentials ใหม่
            device_creds = await self.prisma.devicecredentials.create(
                data={
                    "userId": user_id,
                    "deviceUsername": data.device_username,
                    "devicePasswordHash": password_hash
                }
            )
            
            return DeviceCredentialsResponse(
                id=device_creds.id,
                user_id=device_creds.userId,
                device_username=device_creds.deviceUsername,
                has_password=True,
                created_at=device_creds.createdAt,
                updated_at=device_creds.updatedAt
            )
            
        except Exception as e:
            print(f"Error creating device credentials: {e}")
            raise e
    
    async def update_device_credentials(self, user_id: str, data: DeviceCredentialsUpdate) -> Optional[DeviceCredentialsResponse]:
        """อัปเดต Device Credentials"""
        try:
            # ตรวจสอบว่า device credentials มีอยู่หรือไม่
            existing = await self.prisma.devicecredentials.find_unique(
                where={"userId": user_id}
            )
            
            if not existing:
                raise ValueError("ไม่พบ Device Credentials กรุณาสร้างใหม่ก่อน")
            
            # เตรียมข้อมูลสำหรับอัปเดต
            update_data: Dict[str, Any] = {}
            
            if data.device_username is not None:
                update_data["deviceUsername"] = data.device_username
            
            if data.device_password is not None:
                update_data["devicePasswordHash"] = self._hash_password(data.device_password)
            
            # ตรวจสอบว่ามีข้อมูลที่จะอัปเดตหรือไม่
            if not update_data:
                raise ValueError("ไม่มีข้อมูลที่จะอัปเดต กรุณาระบุ device_username หรือ device_password")
            
            # อัปเดต device credentials
            device_creds = await self.prisma.devicecredentials.update(
                where={"userId": user_id},
                data=update_data
            )
            
            return DeviceCredentialsResponse(
                id=device_creds.id,
                user_id=device_creds.userId,
                device_username=device_creds.deviceUsername,
                has_password=bool(device_creds.devicePasswordHash),
                created_at=device_creds.createdAt,
                updated_at=device_creds.updatedAt
            )
            
        except Exception as e:
            print(f"Error updating device credentials: {e}")
            raise e
    
    async def delete_device_credentials(self, user_id: str) -> bool:
        """ลบ Device Credentials"""
        try:
            # ตรวจสอบว่า device credentials มีอยู่หรือไม่
            existing = await self.prisma.devicecredentials.find_unique(
                where={"userId": user_id}
            )
            
            if not existing:
                raise ValueError("ไม่พบ Device Credentials ที่จะลบ")
            
            # ลบ device credentials
            await self.prisma.devicecredentials.delete(
                where={"userId": user_id}
            )
            
            return True
            
        except Exception as e:
            print(f"Error deleting device credentials: {e}")
            raise e
    
    async def verify_device_credentials(self, user_id: str, username: str, password: str) -> bool:
        """ตรวจสอบ Device Credentials สำหรับการเข้าใช้งาน"""
        try:
            device_creds = await self.prisma.devicecredentials.find_unique(
                where={"userId": user_id}
            )
            
            if not device_creds:
                return False
            
            # ตรวจสอบ username และ password
            if device_creds.deviceUsername != username:
                return False
            
            return self._verify_password(password, device_creds.devicePasswordHash)
            
        except Exception as e:
            print(f"Error verifying device credentials: {e}")
            return False
