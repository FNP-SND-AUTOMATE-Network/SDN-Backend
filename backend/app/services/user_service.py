import bcrypt
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import os
from jose import jwt
from jose.exceptions import JWTError, JWSError, JWEError, JOSEError
from app.models.auth import RegisterRequest
from app.models.user import UserCreateRequest, UserUpdateRequest, UserFilter


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
        except (JWTError, JWSError, JWEError, JOSEError) as e:
            raise ValueError(f"Invalid token: {str(e)}")
    
    def verify_token(self, token: str) -> dict:
        """ตรวจสอบ JWT token และคืนค่า payload ทั้งหมด"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except (JWTError, JWSError, JWEError, JOSEError) as e:
            raise ValueError(f"Invalid token: {str(e)}")

    
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
    
    # ========= CRUD Operations =========
    
    async def create_user_by_admin(self, user_data: UserCreateRequest, otp_service=None) -> dict:
        """สร้าง user ใหม่โดย admin (ต้องยืนยัน OTP ก่อนเปลี่ยน role)"""
        try:
            # ตรวจสอบว่า email มีอยู่แล้วหรือไม่
            existing_user = await self.check_email_exists(user_data.email)
            if existing_user:
                raise ValueError("อีเมลนี้มีอยู่ในระบบแล้ว")
            
            # เข้ารหัสรหัสผ่าน
            hashed_password = self.hash_password(user_data.password)
            
            # สร้าง user ใหม่ แต่เป็น VIEWER เสมอ และ emailVerified = False
            new_user = await self.prisma.user.create(
                data={
                    "email": user_data.email,
                    "name": user_data.name,
                    "surname": user_data.surname,
                    "password": hashed_password,
                    "role": "VIEWER",  # เริ่มต้นเป็น VIEWER เสมอ
                    "emailVerified": False,  # ต้องยืนยัน OTP ก่อน
                    "hasStrongMfa": False
                }
            )
            
            # สร้าง OTP และส่งอีเมล
            if otp_service:
                try:
                    otp_code, expires_at = await otp_service.create_otp_record(user_data.email)
                    email_sent = await otp_service.send_otp_email(
                        user_data.email, 
                        otp_code, 
                        user_data.name or "", 
                        user_data.surname or ""
                    )
                    
                    if not email_sent:
                        # หากส่งอีเมลไม่ได้ ลบ user ที่สร้างไว้
                        await self.prisma.user.delete(where={"id": new_user.id})
                        raise ValueError("ไม่สามารถส่งอีเมลยืนยันได้ กรุณาลองใหม่อีกครั้ง")
                    
                    return {
                        "id": new_user.id,
                        "email": new_user.email,
                        "name": new_user.name,
                        "surname": new_user.surname,
                        "role": new_user.role,
                        "email_verified": new_user.emailVerified,
                        "has_strong_mfa": new_user.hasStrongMfa,
                        "created_at": new_user.createdAt,
                        "updated_at": new_user.updatedAt,
                        "target_role": user_data.role,  # role ที่ต้องการหลังจากยืนยัน OTP
                        "otp_expires_at": expires_at,
                        "requires_otp_verification": True
                    }
                except Exception as otp_error:
                    # หากเกิดข้อผิดพลาดในการส่ง OTP ลบ user ที่สร้างไว้
                    await self.prisma.user.delete(where={"id": new_user.id})
                    raise ValueError(f"ไม่สามารถส่งอีเมลยืนยันได้: {str(otp_error)}")
            else:
                raise ValueError("OTP service is required for user creation")
            
        except Exception as e:
            print(f"Error creating user by admin: {e}")
            raise e
    
    async def get_users_list(self, page: int = 1, page_size: int = 10, filters: Optional[UserFilter] = None) -> dict:
        """ดึงรายการ users พร้อม pagination และ filtering"""
        try:
            # สร้าง where clause สำหรับ filtering
            where_clause = {}
            
            if filters:
                if filters.email:
                    where_clause["email"] = {"contains": filters.email, "mode": "insensitive"}
                if filters.name:
                    where_clause["name"] = {"contains": filters.name, "mode": "insensitive"}
                if filters.surname:
                    where_clause["surname"] = {"contains": filters.surname, "mode": "insensitive"}
                if filters.role:
                    where_clause["role"] = filters.role
                if filters.email_verified is not None:
                    where_clause["emailVerified"] = filters.email_verified
                if filters.has_strong_mfa is not None:
                    where_clause["hasStrongMfa"] = filters.has_strong_mfa
                if filters.search:
                    # ค้นหาใน email, name, surname
                    where_clause["OR"] = [
                        {"email": {"contains": filters.search, "mode": "insensitive"}},
                        {"name": {"contains": filters.search, "mode": "insensitive"}},
                        {"surname": {"contains": filters.search, "mode": "insensitive"}}
                    ]
            
            # นับจำนวนรวม
            total = await self.prisma.user.count(where=where_clause)
            
            # คำนวณ pagination
            skip = (page - 1) * page_size
            total_pages = (total + page_size - 1) // page_size
            
            # ดึงข้อมูล users
            users = await self.prisma.user.find_many(
                where=where_clause,
                skip=skip,
                take=page_size,
                order={
                    "createdAt": "desc"
                }
            )
            
            users_list = []
            for user in users:
                users_list.append({
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "surname": user.surname,
                    "role": user.role,
                    "email_verified": user.emailVerified,
                    "has_strong_mfa": user.hasStrongMfa,
                    "created_at": user.createdAt,
                    "updated_at": user.updatedAt
                })
            
            return {
                "users": users_list,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            }
            
        except Exception as e:
            print(f"Error getting users list: {e}")
            raise e
    
    async def get_user_detail_by_id(self, user_id: str) -> Optional[dict]:
        """ดึงข้อมูลรายละเอียด user รวมทั้ง MFA info"""
        try:
            user = await self.prisma.user.find_unique(
                where={"id": user_id},
                include={
                    "totp": True,
                    "passkeys": True,
                    "recoveryCodes": True
                }
            )
            
            if not user:
                return None
            
            return {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "surname": user.surname,
                "role": user.role,
                "email_verified": user.emailVerified,
                "has_strong_mfa": user.hasStrongMfa,
                "created_at": user.createdAt,
                "updated_at": user.updatedAt,
                "totp_enabled": user.totp is not None,
                "passkeys_count": len(user.passkeys),
                "recovery_codes_count": len(user.recoveryCodes)
            }
            
        except Exception as e:
            print(f"Error getting user detail: {e}")
            return None
    
    async def update_user_by_id(self, user_id: str, update_data: UserUpdateRequest) -> Optional[dict]:
        """อัปเดตข้อมูล user"""
        try:
            # ตรวจสอบว่า user มีอยู่จริง
            existing_user = await self.prisma.user.find_unique(where={"id": user_id})
            if not existing_user:
                raise ValueError("ไม่พบผู้ใช้งาน")
            
            # ตรวจสอบ email ซ้ำ (ถ้ามีการเปลี่ยน email)
            if update_data.email and update_data.email != existing_user.email:
                email_exists = await self.check_email_exists(update_data.email)
                if email_exists:
                    raise ValueError("อีเมลนี้มีอยู่ในระบบแล้ว")
            
            # ตรวจสอบการเปลี่ยน role - ต้องยืนยัน email ก่อน
            if update_data.role and update_data.role != existing_user.role:
                if not existing_user.emailVerified:
                    raise ValueError("ต้องยืนยันอีเมลก่อนเปลี่ยน role")
            
            # เตรียมข้อมูลสำหรับ update
            update_dict = {"updatedAt": datetime.now()}
            
            if update_data.email:
                update_dict["email"] = update_data.email
            if update_data.name is not None:
                update_dict["name"] = update_data.name
            if update_data.surname is not None:
                update_dict["surname"] = update_data.surname
            if update_data.role:
                update_dict["role"] = update_data.role
            if update_data.email_verified is not None:
                update_dict["emailVerified"] = update_data.email_verified
            if update_data.has_strong_mfa is not None:
                update_dict["hasStrongMfa"] = update_data.has_strong_mfa
            
            # อัปเดต user
            updated_user = await self.prisma.user.update(
                where={"id": user_id},
                data=update_dict
            )
            
            return {
                "id": updated_user.id,
                "email": updated_user.email,
                "name": updated_user.name,
                "surname": updated_user.surname,
                "role": updated_user.role,
                "email_verified": updated_user.emailVerified,
                "has_strong_mfa": updated_user.hasStrongMfa,
                "created_at": updated_user.createdAt,
                "updated_at": updated_user.updatedAt
            }
            
        except Exception as e:
            print(f"Error updating user: {e}")
            raise e
    
    async def promote_user_role_after_verification(self, user_id: str, target_role: str) -> Optional[dict]:
        """เปลี่ยน role ของ user หลังจากยืนยัน OTP แล้ว"""
        try:
            # ตรวจสอบว่า user มีอยู่จริงและยืนยัน email แล้ว
            existing_user = await self.prisma.user.find_unique(where={"id": user_id})
            if not existing_user:
                raise ValueError("ไม่พบผู้ใช้งาน")
            
            if not existing_user.emailVerified:
                raise ValueError("ต้องยืนยันอีเมลก่อนเปลี่ยน role")
            
            # อัปเดต role
            updated_user = await self.prisma.user.update(
                where={"id": user_id},
                data={
                    "role": target_role,
                    "updatedAt": datetime.now()
                }
            )
            
            return {
                "id": updated_user.id,
                "email": updated_user.email,
                "name": updated_user.name,
                "surname": updated_user.surname,
                "role": updated_user.role,
                "email_verified": updated_user.emailVerified,
                "has_strong_mfa": updated_user.hasStrongMfa,
                "created_at": updated_user.createdAt,
                "updated_at": updated_user.updatedAt
            }
            
        except Exception as e:
            print(f"Error promoting user role: {e}")
            raise e
    
    async def delete_user_by_id(self, user_id: str) -> bool:
        """ลบ user (soft delete หรือ hard delete ตามความต้องการ)"""
        try:
            # ตรวจสอบว่า user มีอยู่จริง
            existing_user = await self.prisma.user.find_unique(where={"id": user_id})
            if not existing_user:
                raise ValueError("ไม่พบผู้ใช้งาน")
            
            # ลบข้อมูลที่เกี่ยวข้องก่อน (cascade delete)
            await self.prisma.emailotp.delete_many(where={"userId": user_id})
            await self.prisma.recoverycode.delete_many(where={"userId": user_id})
            await self.prisma.webauthncredential.delete_many(where={"userId": user_id})
            
            # ลบ TOTP ถ้ามี
            await self.prisma.usertotp.delete_many(where={"userId": user_id})
            
            # ลบ user
            await self.prisma.user.delete(where={"id": user_id})
            
            return True
            
        except Exception as e:
            print(f"Error deleting user: {e}")
            raise e
    
    async def change_user_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        """เปลี่ยนรหัสผ่าน user (ตรวจสอบรหัสผ่านเก่า)"""
        try:
            # ดึงข้อมูล user
            user = await self.prisma.user.find_unique(where={"id": user_id})
            if not user:
                raise ValueError("ไม่พบผู้ใช้งาน")
            
            # ตรวจสอบรหัสผ่านเก่า
            if not self.verify_password(current_password, user.password):
                raise ValueError("รหัสผ่านปัจจุบันไม่ถูกต้อง")
            
            # เข้ารหัสรหัสผ่านใหม่
            new_hashed_password = self.hash_password(new_password)
            
            # อัปเดตรหัสผ่าน
            await self.prisma.user.update(
                where={"id": user_id},
                data={
                    "password": new_hashed_password,
                    "updatedAt": datetime.now()
                }
            )
            
            return True
            
        except Exception as e:
            print(f"Error changing password: {e}")
            raise e
    
    async def reset_user_password_by_admin(self, user_id: str, new_password: str) -> bool:
        """รีเซ็ตรหัสผ่าน user โดย admin (ไม่ต้องตรวจสอบรหัสผ่านเก่า)"""
        try:
            # ตรวจสอบว่า user มีอยู่จริง
            user = await self.prisma.user.find_unique(where={"id": user_id})
            if not user:
                raise ValueError("ไม่พบผู้ใช้งาน")
            
            # เข้ารหัสรหัสผ่านใหม่
            new_hashed_password = self.hash_password(new_password)
            
            # อัปเดตรหัสผ่าน
            await self.prisma.user.update(
                where={"id": user_id},
                data={
                    "password": new_hashed_password,
                    "updatedAt": datetime.now()
                }
            )
            
            return True
            
        except Exception as e:
            print(f"Error resetting password by admin: {e}")
            raise e
