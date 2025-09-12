import bcrypt
from datetime import datetime, timedelta
from typing import Optional
import os
from jose import jwt
from app.models.auth import RegisterRequest


class UserService:
    def __init__(self, prisma_client=None):
        self.prisma = prisma_client
        self.secret_key = os.getenv("SECRET_KEY")
        self.algorithm = os.getenv("ALGORITHM", "HS256")
        self.access_token_expire_minutes = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    
    def hash_password(self, password: str) -> str:
        """เข้ารหัสรหัสผ่าน"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    async def create_user(self, register_data: RegisterRequest) -> dict:
        """สร้าง user ใหม่หลังจากยืนยัน OTP แล้ว"""
        
        # หา temporary user ที่สร้างไว้ตอนส่ง OTP
        temp_user = await self.prisma.user.find_unique(where={"email": register_data.email})
        
        if not temp_user:
            raise ValueError("ไม่พบข้อมูลการสมัครสมาชิก")
        
        # อัปเดตข้อมูล user
        hashed_password = self.hash_password(register_data.password)
        
        updated_user = await self.prisma.user.update(
            where={"id": temp_user.id},
            data={
                "name": register_data.name,
                "surname": register_data.surname,
                "password": hashed_password,
                "emailVerified": True,
                "updatedAt": datetime.now()
            }
        )
        
        # ลบ OTP records ที่เกี่ยวข้อง
        await self.prisma.emailotp.delete_many(
            where={
                "userId": temp_user.id,
                "purpose": "VERIFY_EMAIL"
            }
        )
        
        
        return {
            "id": updated_user.id,
            "email": updated_user.email,
            "name": updated_user.name,
            "surname": updated_user.surname,
            "emailVerified": updated_user.emailVerified,
            "role": updated_user.role
        }
    
    async def check_email_exists(self, email: str) -> bool:
        """ตรวจสอบว่า email มีอยู่ในระบบแล้วหรือไม่"""
        user = await self.prisma.user.find_unique(where={"email": email})
        return user is not None
    
    async def get_user_by_email(self, email: str) -> Optional[dict]:
        """ดึงข้อมูล user จาก email"""
        user = await self.prisma.user.find_unique(where={"email": email})
        
        if user:
            return {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "surname": user.surname,
                "password": user.password,  # เพิ่มสำหรับการตรวจสอบรหัสผ่าน
                "emailVerified": user.emailVerified,
                "role": user.role,
                "createdAt": user.createdAt,
                "updatedAt": user.updatedAt
            }
        return None
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """ตรวจสอบรหัสผ่าน"""
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    
    def create_access_token(self, data: dict) -> str:
        """สร้าง JWT access token"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt
    
    async def authenticate_user(self, email: str, password: str) -> Optional[dict]:
        """ตรวจสอบ email และ password และคืนค่าข้อมูลผู้ใช้"""
        user = await self.get_user_by_email(email)
        
        if not user:
            return None
        
        # ตรวจสอบว่า email ได้รับการยืนยันแล้วหรือไม่
        if not user["emailVerified"]:
            return None
        
        # ตรวจสอบรหัสผ่าน
        if not self.verify_password(password, user["password"]):
            return None
        
        return user
    
    async def verify_access_token(self, token: str) -> str:
        """ตรวจสอบ JWT token และคืนค่า user_id"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            user_id: str = payload.get("sub")
            if user_id is None:
                raise ValueError("Invalid token")
            return user_id
        except jwt.PyJWTError:
            raise ValueError("Invalid token")
    
    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """ดึงข้อมูลผู้ใช้ตาม ID"""
        try:
            user = await self.prisma.user.find_unique(
                where={"id": user_id}
            )
            if user:
                return {
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "surname": user.surname,
                    "emailVerified": user.emailVerified,
                    "role": user.role,
                    "createdAt": user.createdAt,
                    "updatedAt": user.updatedAt
                }
            return None
        except Exception as e:
            print(f"Error getting user by ID: {e}")
            return None
