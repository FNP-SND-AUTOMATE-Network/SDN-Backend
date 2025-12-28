import pyotp
from typing import Optional, Tuple
from prisma import Prisma
from datetime import datetime
import base64

class TotpService:
    def __init__(self, prisma_client: Prisma):
        self.prisma = prisma_client
        self.issuer_name = "FNP SDN"  # ชื่อที่จะแสดงใน Authenticator App

    def generate_secret(self) -> str:
        #สร้าง Random Base32 Secret
        return pyotp.random_base32()

    def get_provisioning_uri(self, secret: str, email: str) -> str:
        #สร้าง otpauth URL สำหรับ QR Code
        return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=self.issuer_name)

    def verify_totp(self, secret: str, code: str) -> bool:
        #ตรวจสอบรหัส TOTP
        totp = pyotp.TOTP(secret)
        return totp.verify(code)

    async def enable_totp(self, user_id: str, secret: str) -> bool:
        #บันทึก Secret และเปิดใช้งาน TOTP
        try:

            secret_bytes = secret.encode('utf-8')
            secret_base64 = base64.b64encode(secret_bytes).decode('utf-8')
            
            existing_totp = await self.prisma.usertotp.find_unique(where={"userId": user_id})

            secret_base64_escaped = secret_base64.replace("'", "''")
            
            if existing_totp:
                await self.prisma.query_raw(
                    f"""
                    UPDATE "UserTotp"
                    SET "secret" = decode('{secret_base64_escaped}', 'base64'),
                        "enabled" = true,
                        "createdAt" = '{datetime.now().isoformat()}'
                    WHERE "userId" = '{user_id}'::uuid
                    """
                )
            else:
                await self.prisma.query_raw(
                    f"""
                    INSERT INTO "UserTotp" ("userId", "secret", "enabled", "createdAt")
                    VALUES ('{user_id}'::uuid, decode('{secret_base64_escaped}', 'base64'), true, '{datetime.now().isoformat()}')
                    """
                )
            
            await self.prisma.user.update(
                where={"id": user_id},
                data={"hasStrongMfa": True}
            )

            return True
        except Exception as e:
            import traceback
            error_detail = f"Error enabling TOTP: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            print(error_detail)
            return False

    async def disable_totp(self, user_id: str) -> bool:
        #ปิดการใช้งาน TOTP
        try:
            existing_totp = await self.prisma.usertotp.find_unique(where={"userId": user_id})
            
            if existing_totp:
                await self.prisma.usertotp.delete(where={"userId": user_id})
            
            await self.prisma.user.update(
                where={"id": user_id},
                data={"hasStrongMfa": False}
            )
            
            return True
        except Exception as e:
            import traceback
            error_detail = f"Error disabling TOTP: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            print(error_detail)
            return False

    async def get_user_totp_secret(self, user_id: str) -> Optional[str]:
        #ดึง Secret ของ User (สำหรับตรวจสอบตอน Login)
        try:
            print(f"[DEBUG] Getting TOTP secret for user_id: {user_id}")
            totp_record = await self.prisma.usertotp.find_unique(where={"userId": user_id})
            
            print(f"[DEBUG] TOTP record found: {totp_record is not None}")
            if totp_record:
                print(f"[DEBUG] TOTP enabled: {totp_record.enabled}")
                print(f"[DEBUG] Secret type: {type(totp_record.secret)}")
                print(f"[DEBUG] Secret dir: {dir(totp_record.secret)}")
            
            if not totp_record or not totp_record.enabled:
                print(f"[DEBUG] Returning None - no record or not enabled")
                return None
            
            # Prisma Base64 object เก็บ base64 string ไว้ใน attribute
            # ลองหลายวิธี: __str__, __bytes__, หรือ attribute ที่ซ่อนอยู่
            secret_data = totp_record.secret
            
            # วิธีที่ 1: ลอง access raw bytes ผ่าน __bytes__
            try:
                if hasattr(secret_data, '__bytes__'):
                    secret_bytes = secret_data.__bytes__()
                    print(f"[DEBUG] Got bytes via __bytes__: {len(secret_bytes)} bytes")
                    secret = secret_bytes.decode('utf-8')
                    print(f"[DEBUG] Decoded to string: {len(secret)} chars")
                    return secret
            except Exception as e1:
                print(f"[DEBUG] __bytes__ failed: {e1}")
            
            # วิธีที่ 2: ลอง convert เป็น str แล้ว decode base64
            try:
                secret_str = str(secret_data)
                print(f"[DEBUG] Converted to str: {secret_str[:20]}...")
                # ถ้า str เป็น base64 encoded ให้ decode
                secret_bytes = base64.b64decode(secret_str)
                secret = secret_bytes.decode('utf-8')
                print(f"[DEBUG] Decoded from base64 string: {len(secret)} chars")
                return secret
            except Exception as e2:
                print(f"[DEBUG] base64 decode failed: {e2}")
            
            # วิธีที่ 3: ถ้าเป็น bytes object โดยตรง
            if isinstance(secret_data, bytes):
                secret = secret_data.decode('utf-8')
                print(f"[DEBUG] Direct bytes decode: {len(secret)} chars")
                return secret
            
            print(f"[ERROR] All decode methods failed")
            return None
            
        except Exception as e:
            import traceback
            error_detail = f"Error getting TOTP secret: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            print(f"[ERROR] {error_detail}")
            return None
