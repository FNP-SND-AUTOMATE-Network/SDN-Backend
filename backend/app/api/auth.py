from fastapi import APIRouter, HTTPException, status
from app.models.auth import RegisterRequest, RegisterResponse, VerifyOtpRequest, VerifyOtpResponse, ResendOtpRequest, ResendOtpResponse, LoginRequest, LoginResponse, ErrorResponse
from app.services.otp_service import OtpService
from app.services.user_service import UserService
from datetime import datetime

router = APIRouter(prefix="/auth", tags=["Authentication"])

otp_service = OtpService()
user_service = UserService()


@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest):
    """
    สมัครสมาชิกใหม่ - สร้าง OTP และส่งอีเมลยืนยัน
    """
    try:
        # ตรวจสอบว่า email มีอยู่ในระบบแล้วหรือไม่
        email_exists = await user_service.check_email_exists(request.email)
        if email_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="อีเมลนี้มีอยู่ในระบบแล้ว"
            )
        
        # สร้าง temporary user และ OTP
        from prisma import Prisma
        prisma = Prisma()
        await prisma.connect()
        
        # สร้าง temporary user
        temp_user = await prisma.user.create(
            data={
                "email": request.email,
                "name": request.name,
                "surname": request.surname,
                "password": user_service.hash_password(request.password),
                "emailVerified": False
            }
        )
        
        # สร้าง OTP
        otp_code, expires_at = await otp_service.create_otp_record(request.email)
        
        await prisma.disconnect()
        
        # ส่ง OTP ผ่านอีเมล
        email_sent = await otp_service.send_otp_email(request.email, otp_code, request.name, request.surname)
        
        if not email_sent:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถส่งอีเมลยืนยันได้ กรุณาลองใหม่อีกครั้ง"
            )
        
        return RegisterResponse(
            message="ส่งรหัสยืนยันไปยังอีเมลของคุณแล้ว กรุณาตรวจสอบอีเมลและยืนยันการสมัครสมาชิก",
            email=request.email,
            expires_at=expires_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการสมัครสมาชิก: {str(e)}"
        )


@router.post("/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp(request: VerifyOtpRequest):
    """
    ยืนยัน OTP และสร้างบัญชีผู้ใช้
    """
    try:
        # ตรวจสอบ OTP
        user_id = await otp_service.verify_otp(request.email, request.otp_code)
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="รหัสยืนยันไม่ถูกต้องหรือหมดอายุแล้ว กรุณาลองใหม่อีกครั้ง"
            )
        
        # ดึงข้อมูล user ที่สร้างไว้ชั่วคราว
        temp_user = await user_service.get_user_by_email(request.email)
        
        if not temp_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ไม่พบข้อมูลการสมัครสมาชิก กรุณาสมัครสมาชิกใหม่"
            )
        
        # อัปเดตสถานะ emailVerified เป็น True
        from prisma import Prisma
        prisma = Prisma()
        await prisma.connect()
        
        updated_user = await prisma.user.update(
            where={"id": user_id},
            data={"emailVerified": True}
        )
        
        await prisma.disconnect()
        
        return VerifyOtpResponse(
            message="ยืนยันการสมัครสมาชิกเรียบร้อยแล้ว",
            user_id=updated_user.id,
            email=updated_user.email,
            email_verified=True
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการยืนยัน: {str(e)}"
        )


@router.post("/resend-otp", response_model=ResendOtpResponse)
async def resend_otp(request: ResendOtpRequest):
    """
    ส่ง OTP ใหม่เมื่อรหัสเดิมหมดอายุ
    """
    try:
        # ตรวจสอบว่า email มีอยู่ในระบบและยังไม่ได้ยืนยัน
        user = await user_service.get_user_by_email(request.email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ไม่พบข้อมูลการสมัครสมาชิก กรุณาสมัครสมาชิกใหม่"
            )
        
        if user["emailVerified"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="อีเมลนี้ได้รับการยืนยันแล้ว"
            )
        
        # สร้าง OTP ใหม่
        otp_code, expires_at = await otp_service.create_otp_record(request.email)
        
        # ส่ง OTP ผ่านอีเมล (ใช้ name และ surname จาก database)
        email_sent = await otp_service.send_otp_email(request.email, otp_code, user["name"] or "", user["surname"] or "")
        
        if not email_sent:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถส่งอีเมลยืนยันได้ กรุณาลองใหม่อีกครั้ง"
            )
        
        return ResendOtpResponse(
            message="ส่งรหัสยืนยันใหม่ไปยังอีเมลของคุณแล้ว กรุณาตรวจสอบอีเมลและยืนยันการสมัครสมาชิก",
            email=request.email,
            expires_at=expires_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการส่งรหัสยืนยันใหม่: {str(e)}"
        )


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    เข้าสู่ระบบด้วย email และ password
    """
    try:
        # ตรวจสอบข้อมูลผู้ใช้และรหัสผ่าน
        user = await user_service.authenticate_user(request.email, request.password)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง หรือยังไม่ได้ยืนยันอีเมล"
            )
        
        # สร้าง JWT token
        access_token_data = {
            "sub": user["email"],
            "user_id": user["id"],
            "role": user["role"]
        }
        access_token = user_service.create_access_token(access_token_data)
        
        return LoginResponse(
            message="เข้าสู่ระบบสำเร็จ",
            access_token=access_token,
            token_type="bearer",
            user_id=user["id"],
            email=user["email"],
            name=user["name"],
            surname=user["surname"],
            role=user["role"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการเข้าสู่ระบบ: {str(e)}"
        )
