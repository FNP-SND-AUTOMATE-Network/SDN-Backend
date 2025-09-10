import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional
import bcrypt
import os


class OtpService:
    def __init__(self):
        self.resend_api_key = os.getenv("RESEND_API_KEY")
        self.resend_api_url = os.getenv("RESEND_API_URL")
    
    @property
    def prisma(self):
        # Use global client from main.py
        from app.main import prisma_client
        return prisma_client
    
    async def generate_otp(self) -> str:
        """สร้าง OTP 6 หลัก"""
        return str(secrets.randbelow(900000) + 100000)
    
    def hash_otp(self, otp: str) -> str:
        """เข้ารหัส OTP"""
        return hashlib.sha256(otp.encode()).hexdigest()
    
    async def create_otp_record(self, email: str, purpose: str = "VERIFY_EMAIL") -> tuple[str, datetime]:
        """สร้าง OTP record ในฐานข้อมูล"""
        
        # ลบ OTP เก่าที่หมดอายุแล้ว
        await self.prisma.emailotp.delete_many(
            where={
                "expiresAt": {"lt": datetime.now()},
                "purpose": purpose
            }
        )
        
        # สร้าง OTP ใหม่
        otp_code = await self.generate_otp()
        otp_hash = self.hash_otp(otp_code)
        expires_at = datetime.now() + timedelta(minutes=10)  # หมดอายุใน 10 นาที
        
        # หา user จาก email (ควรมีอยู่แล้วจากขั้นตอน register)
        user = await self.prisma.user.find_unique(where={"email": email})
        
        if not user:
            raise ValueError("ไม่พบข้อมูลผู้ใช้")
        
        # สร้าง OTP record
        await self.prisma.emailotp.create(
            data={
                "userId": user.id,
                "codeHash": otp_hash,
                "purpose": purpose,
                "expiresAt": expires_at
            }
        )
        
        return otp_code, expires_at
    
    async def verify_otp(self, email: str, otp_code: str, purpose: str = "VERIFY_EMAIL") -> Optional[str]:
        """ตรวจสอบ OTP และคืนค่า user_id ถ้าถูกต้อง"""
        
        # หา user จาก email
        user = await self.prisma.user.find_unique(where={"email": email})
        if not user:
            return None
        
        # หา OTP record ที่ยังไม่หมดอายุและยังไม่ถูกใช้
        otp_hash = self.hash_otp(otp_code)
        otp_record = await self.prisma.emailotp.find_first(
            where={
                "userId": user.id,
                "codeHash": otp_hash,
                "purpose": purpose,
                "expiresAt": {"gt": datetime.now()},
                "consumedAt": None
            }
        )
        
        if not otp_record:
            return None
        
        # ทำเครื่องหมายว่า OTP ถูกใช้แล้ว
        await self.prisma.emailotp.update(
            where={"id": otp_record.id},
            data={"consumedAt": datetime.now()}
        )
        
        return user.id
    
    async def send_otp_email(self, email: str, otp_code: str, name: str, surname: str) -> bool:
        """ส่ง OTP ผ่าน email"""
        try:
            import requests
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>ยืนยันการสมัครสมาชิก</title>
            </head>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #2c3e50;">ยืนยันการสมัครสมาชิก</h2>
                    <p>สวัสดีครับ คุณ {name} {surname}</p>
                    <p>ขอบคุณที่สมัครสมาชิกกับเรา กรุณาใช้รหัสยืนยันด้านล่างเพื่อยืนยันการสมัครสมาชิก:</p>
                    
                    <div style="background-color: #f8f9fa; border: 2px solid #dee2e6; border-radius: 8px; padding: 20px; text-align: center; margin: 20px 0;">
                        <h1 style="color: #007bff; font-size: 32px; margin: 0; letter-spacing: 5px;">{otp_code}</h1>
                    </div>
                    
                    <p><strong>หมายเหตุ:</strong></p>
                    <ul>
                        <li>รหัสนี้จะหมดอายุใน 10 นาที</li>
                        <li>ห้ามแชร์รหัสนี้กับผู้อื่น</li>
                        <li>หากคุณไม่ได้สมัครสมาชิก กรุณาเพิกเฉยต่ออีเมลนี้</li>
                    </ul>
                    
                    <p>หากมีข้อสงสัย กรุณาติดต่อทีม noppadol.p.promtas@gmail.com</p>
                    <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
                    <p style="font-size: 12px; color: #666;">อีเมลนี้ถูกส่งโดยระบบอัตโนมัติ กรุณาอย่าตอบกลับ</p>
                </div>
            </body>
            </html>
            """
            
            # ใช้ Resend API โดยตรง
            url = self.resend_api_url
            headers = {
                "Authorization": f"Bearer {self.resend_api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "from": "support@notify.au-nongtota.com",  # ใช้ Resend test domain
                "to": [email],
                "subject": "ยืนยันการสมัครสมาชิก - รหัส OTP",
                "html": html_content,
                "reply_to": "support@notify.au-nongtota.com"
            }
            
            response = requests.post(url, json=data, headers=headers)
            
            if response.status_code == 200:
                print(f"Email sent successfully to {email}")
                return True
            else:
                print(f"Failed to send email. Status: {response.status_code}, Response: {response.text}")
                return False
            
        except Exception as e:
            print(f"Error sending email: {e}")
            return False
    
    async def cleanup_expired_otps(self):
        """ลบ OTP ที่หมดอายุแล้ว"""
        await self.prisma.emailotp.delete_many(
            where={"expiresAt": {"lt": datetime.now()}}
        )
