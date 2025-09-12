from fastapi import APIRouter, HTTPException, status, Request
from app.models.auth import RegisterRequest, RegisterResponse, VerifyOtpRequest, VerifyOtpResponse, ResendOtpRequest, ResendOtpResponse, LoginRequest, LoginResponse, ErrorResponse
from app.services.otp_service import OtpService
from app.services.user_service import UserService
from app.services.audit_service import AuditService
from datetime import datetime

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ใช้ global prisma client จาก database.py
from app.database import get_prisma_client, is_prisma_client_ready

# Services จะได้รับ prisma client ใน runtime
otp_service = None
user_service = None
audit_service = None

# Initialize services with prisma client
def get_services():
    """Get initialized services, creating them if needed"""
    global otp_service, user_service, audit_service
    
    # Initialize services if not already done
    if otp_service is None or user_service is None or audit_service is None:
        if not is_prisma_client_ready():
            raise HTTPException(
                status_code=500,
                detail="Database connection not ready. Please try again."
            )
        
        prisma_client = get_prisma_client()
        otp_service = OtpService(prisma_client)
        user_service = UserService(prisma_client)
        audit_service = AuditService(prisma_client)
    
    return otp_service, user_service, audit_service


@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest):
    """
    สมัครสมาชิกใหม่ - สร้าง OTP และส่งอีเมลยืนยัน
    """
    try:
        # Get initialized services
        otp_svc, user_svc, audit_svc = get_services()
        
        # ตรวจสอบว่า email มีอยู่ในระบบแล้วหรือไม่
        email_exists = await user_svc.check_email_exists(request.email)
        if email_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="อีเมลนี้มีอยู่ในระบบแล้ว"
            )
        
        # ใช้ global prisma client แทนการสร้างใหม่
        prisma_client = get_prisma_client()
        
        # สร้าง temporary user
        temp_user = await prisma_client.user.create(
            data={
                "email": request.email,
                "name": request.name,
                "surname": request.surname,
                "password": user_svc.hash_password(request.password),
                "emailVerified": False
            }
        )
        
        # สร้าง OTP
        otp_code, expires_at = await otp_svc.create_otp_record(request.email)
        
        # ส่ง OTP ผ่านอีเมล
        email_sent = await otp_svc.send_otp_email(request.email, otp_code, request.name, request.surname)
        
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
async def verify_otp(request: VerifyOtpRequest, req: Request):
    """
    ยืนยัน OTP และสร้างบัญชีผู้ใช้
    """
    try:
        # Get initialized services
        otp_svc, user_svc, audit_svc = get_services()
        
        # ตรวจสอบ OTP
        user_id = await otp_svc.verify_otp(request.email, request.otp_code)
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="รหัสยืนยันไม่ถูกต้องหรือหมดอายุแล้ว กรุณาลองใหม่อีกครั้ง"
            )
        
        # ดึงข้อมูล user ที่สร้างไว้ชั่วคราว
        temp_user = await user_svc.get_user_by_email(request.email)
        
        if not temp_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ไม่พบข้อมูลการสมัครสมาชิก กรุณาสมัครสมาชิกใหม่"
            )
        
        # อัปเดตสถานะ emailVerified เป็น True ใช้ global client
        prisma_client = get_prisma_client()
        updated_user = await prisma_client.user.update(
            where={"id": user_id},
            data={"emailVerified": True}
        )
        
        # สร้าง audit log สำหรับการสมัครสมาชิกสำเร็จ
        try:
            # ดึง IP address
            client_ip = req.client.host
            if "x-forwarded-for" in req.headers:
                client_ip = req.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in req.headers:
                client_ip = req.headers["x-real-ip"]
            
            user_agent = req.headers.get("user-agent")
            
            await audit_svc.create_register_audit(
                user_id=updated_user.id,
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as audit_error:
            print(f"Error creating register audit log: {audit_error}")
            # ไม่ให้ audit error หยุดการทำงานหลัก
        
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
        # Get initialized services
        otp_svc, user_svc, audit_svc = get_services()
        
        # ตรวจสอบว่า email มีอยู่ในระบบและยังไม่ได้ยืนยัน
        user = await user_svc.get_user_by_email(request.email)
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
        otp_code, expires_at = await otp_svc.create_otp_record(request.email)
        
        # ส่ง OTP ผ่านอีเมล (ใช้ name และ surname จาก database)
        email_sent = await otp_svc.send_otp_email(request.email, otp_code, user["name"] or "", user["surname"] or "")
        
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
async def login(request: LoginRequest, req: Request):
    """
    เข้าสู่ระบบด้วย email และ password
    """
    try:
        # Get initialized services
        otp_svc, user_svc, audit_svc = get_services()
        
        # ตรวจสอบข้อมูลผู้ใช้และรหัสผ่าน
        user = await user_svc.authenticate_user(request.email, request.password)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง หรือยังไม่ได้ยืนยันอีเมล"
            )
        
        # สร้าง JWT token
        access_token_data = {
            "sub": user["id"],  # ใช้ user_id แทน email สำหรับ JWT sub
            "user_id": user["id"],
            "role": user["role"]
        }
        access_token = user_svc.create_access_token(access_token_data)
        
        # สร้าง audit log สำหรับการ login สำเร็จ
        try:
            # ดึง IP address
            client_ip = req.client.host
            if "x-forwarded-for" in req.headers:
                client_ip = req.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in req.headers:
                client_ip = req.headers["x-real-ip"]
            
            user_agent = req.headers.get("user-agent")
            
            await audit_svc.create_login_audit(
                user_id=user["id"],
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as audit_error:
            print(f"Error creating login audit log: {audit_error}")
            # ไม่ให้ audit error หยุดการทำงานหลัก
        
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
