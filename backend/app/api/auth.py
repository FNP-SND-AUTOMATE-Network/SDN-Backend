from fastapi import APIRouter, HTTPException, status, Request
from app.models.auth import (
    RegisterRequest, RegisterResponse, VerifyOtpRequest, VerifyOtpResponse, 
    ResendOtpRequest, ResendOtpResponse, LoginRequest, LoginResponse, ErrorResponse,
    TotpSetupResponse, TotpVerifyRequest, TotpDisableRequest, VerifyTotpLoginRequest
)
from app.services.otp_service import OtpService
from app.services.user_service import UserService
from app.services.audit_service import AuditService
from app.services.totp_service import TotpService
from datetime import datetime
from app.api.users import get_current_user
from fastapi import Depends

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ใช้ global prisma client จาก database.py
from app.database import get_prisma_client, is_prisma_client_ready

# Services จะได้รับ prisma client ใน runtime
otp_service = None
user_service = None
audit_service = None
totp_service = None

# Initialize services with prisma client
def get_services():
    """Get initialized services, creating them if needed"""
    global otp_service, user_service, audit_service, totp_service
    
    # Initialize services if not already done
    if otp_service is None or user_service is None or audit_service is None or totp_service is None:
        if not is_prisma_client_ready():
            raise HTTPException(
                status_code=500,
                detail="Database connection not ready. Please try again."
            )
        
        prisma_client = get_prisma_client()
        otp_service = OtpService(prisma_client)
        user_service = UserService(prisma_client)
        audit_service = AuditService(prisma_client)
        totp_service = TotpService(prisma_client)
    
    return otp_service, user_service, audit_service, totp_service


@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest):
    """
    สมัครสมาชิกใหม่ - สร้าง OTP และส่งอีเมลยืนยัน
    """
    try:
        # Get initialized services
        otp_svc, user_svc, audit_svc, _ = get_services()
        
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
        otp_svc, user_svc, audit_svc, _ = get_services()
        
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
        otp_svc, user_svc, audit_svc, _ = get_services()
        
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
    
    ถ้าเปิดใช้งาน TOTP ไว้ ระบบจะส่ง requires_totp = True พร้อม temp_token
    ต้องเรียกใช้ /auth/mfa-verify-totp-login เพื่อยืนยันรหัส TOTP
    """
    try:
        # Get initialized services
        otp_svc, user_svc, audit_svc, totp_svc = get_services()
        
        # ตรวจสอบข้อมูลผู้ใช้และรหัสผ่าน
        user = await user_svc.authenticate_user(request.email, request.password)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง หรือยังไม่ได้ยืนยันอีเมล"
            )
        
        # ตรวจสอบว่ามีการเปิดใช้งาน TOTP หรือไม่
        print(f"[DEBUG] Checking TOTP for user: {user['id']}")
        totp_secret = await totp_svc.get_user_totp_secret(user["id"])
        print(f"[DEBUG] TOTP secret result: {totp_secret is not None}")
        
        if totp_secret:
            print(f"[DEBUG] Creating temp_token for 2FA")
            # สร้าง temporary token สำหรับยืนยัน TOTP
            temp_token_data = {
                "sub": user["id"],
                "user_id": user["id"],
                "email": user["email"],
                "totp_required": True,
                "exp": datetime.utcnow().timestamp() + 300  # หมดอายุใน 5 นาที
            }
            temp_token = user_svc.create_access_token(temp_token_data)
            print(f"[DEBUG] temp_token created: {temp_token[:20]}...")
            
            return LoginResponse(
                message="กรุณายืนยันรหัส TOTP",
                user_id=user["id"],
                email=user["email"],
                name=user["name"],
                surname=user["surname"],
                role=user["role"],
                requires_totp=True,
                temp_token=temp_token
            )
        
        # ถ้าไม่ต้องใช้ TOTP สร้าง access token ปกติ
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


# ========= MFA / TOTP Endpoints =========

@router.post("/mfa/setup", response_model=TotpSetupResponse)
async def setup_totp(
    current_user: dict = Depends(get_current_user)
):
    """
    ขอ Secret Key และ QR Code URL สำหรับตั้งค่า TOTP
    """
    try:
        _, _, _, totp_svc = get_services()
        
        # สร้าง Secret ใหม่
        secret = totp_svc.generate_secret()
        
        # สร้าง URL สำหรับ QR Code
        provisioning_uri = totp_svc.get_provisioning_uri(secret, current_user["email"])
        
        return TotpSetupResponse(
            secret=secret,
            provisioning_uri=provisioning_uri
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการขอตั้งค่า TOTP: {str(e)}"
        )


@router.post("/mfa/verify", response_model=dict)
async def verify_totp_setup(
    request: TotpVerifyRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    ยืนยันรหัส TOTP เพื่อเปิดใช้งาน
    
    ต้องส่ง JSON body:
    {
        "secret": "xxxxx",      // Secret key ที่ได้จาก /auth/mfa/setup
        "otp_code": "123456"    // รหัส 6 หลักจาก Authenticator App
    }
    
    หมายเหตุ: ต้องส่ง Header "Content-Type: application/json"
    """
    try:
        # Validate request data
        if not request.secret or not request.otp_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="กรุณาส่ง secret และ otp_code ใน request body"
            )
        
        _, _, audit_svc, totp_svc = get_services()
        
        # ตรวจสอบรหัส TOTP
        is_valid = totp_svc.verify_totp(request.secret, request.otp_code)
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="รหัส TOTP ไม่ถูกต้อง หรือหมดอายุแล้ว กรุณาใช้รหัสใหม่"
            )
        
        # บันทึกและเปิดใช้งาน TOTP
        success = await totp_svc.enable_totp(current_user["id"], request.secret)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถเปิดใช้งาน TOTP ได้"
            )
            
        # Audit Log
        try:
            await audit_svc.create_audit_log(
                actor_user_id=current_user["id"],
                action="ENABLE_TOTP",
                details={"method": "TOTP"}
            )
        except Exception as audit_error:
            print(f"Error creating audit log: {audit_error}")
            # ไม่ให้ audit error หยุดการทำงานหลัก
        
        return {"message": "เปิดใช้งาน TOTP เรียบร้อยแล้ว"}
        
    except HTTPException:
        raise
    except ValueError as e:
        # Handle validation errors from Pydantic
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"ข้อมูลไม่ถูกต้อง: {str(e)}"
        )
    except Exception as e:
        print(f"Error in verify_totp_setup: {type(e).__name__}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการยืนยัน TOTP: {str(e)}"
        )




@router.post("/mfa-verify-totp-login", response_model=LoginResponse)
async def verify_totp_login(request: VerifyTotpLoginRequest):
    """
    ยืนยันรหัส TOTP สำหรับการเข้าสู่ระบบ
    
    ต้องส่ง:
    {
        "temp_token": "...",    // Temporary token ที่ได้จาก /auth/login
        "otp_code": "123456"    // รหัส 6 หลักจาก Authenticator App
    }
    
    หมายเหตุ: ต้องส่ง Header "Content-Type: application/json"
    """
    try:
        print(f"[DEBUG] Verifying TOTP login, OTP code: {request.otp_code}")
        # Get initialized services
        _, user_svc, audit_svc, totp_svc = get_services()
        
        # ตรวจสอบ temp token
        try:
            print(f"[DEBUG] Verifying temp_token...")
            token_data = user_svc.verify_token(request.temp_token)
            print(f"[DEBUG] Token data: {token_data}")
            
            if not token_data.get("totp_required"):
                print(f"[DEBUG] Token does not have totp_required flag")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Token ไม่ถูกต้องหรือไม่รองรับการยืนยัน TOTP"
                )
            
            user_id = token_data.get("user_id")
            if not user_id:
                print(f"[DEBUG] No user_id in token")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ไม่พบข้อมูลผู้ใช้ใน Token"
                )
            
            print(f"[DEBUG] Getting user by id: {user_id}")
            # ดึงข้อมูลผู้ใช้
            user = await user_svc.get_user_by_id(user_id)
            if not user:
                print(f"[DEBUG] User not found")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="ไม่พบข้อมูลผู้ใช้"
                )
            
            print(f"[DEBUG] Getting TOTP secret for user")
            # ดึง TOTP secret
            totp_secret = await totp_svc.get_user_totp_secret(user_id)
            if not totp_secret:
                print(f"[DEBUG] No TOTP secret found")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ไม่พบการตั้งค่า TOTP สำหรับผู้ใช้นี้"
                )
            
            print(f"[DEBUG] Verifying TOTP code")
            # ตรวจสอบรหัส TOTP
            is_valid = totp_svc.verify_totp(totp_secret, request.otp_code)
            print(f"[DEBUG] TOTP verification result: {is_valid}")
            
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="รหัส TOTP ไม่ถูกต้องหรือหมดอายุแล้ว กรุณาลองใหม่อีกครั้ง"
                )
            
            print(f"[DEBUG] Creating access token")
            # สร้าง access token จริง
            access_token_data = {
                "sub": user["id"],
                "user_id": user["id"],
                "role": user["role"]
            }
            access_token = user_svc.create_access_token(access_token_data)
            
            # Audit Log
            try:
                await audit_svc.create_audit_log(
                    actor_user_id=user["id"],
                    action="LOGIN_WITH_TOTP",
                    details={"method": "TOTP", "status": "success"}
                )
            except Exception as audit_error:
                print(f"Error creating audit log: {audit_error}")
            
            print(f"[DEBUG] Login successful")
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
            import traceback
            error_detail = f"Token verification error: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            print(f"[ERROR] {error_detail}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token ไม่ถูกต้องหรือหมดอายุแล้ว"
            )

            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in verify_totp_login: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการยืนยัน TOTP: {str(e)}"
        )


@router.post("/mfa/disable", response_model=dict)
async def disable_totp(
    request: TotpDisableRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    ปิดการใช้งาน TOTP (ต้องยืนยันรหัสผ่าน)
    """
    try:
        print(f"[DEBUG] Disable TOTP request: password length = {len(request.password)}")
        _, user_svc, audit_svc, totp_svc = get_services()
        
        # ตรวจสอบรหัสผ่านเพื่อความปลอดภัย
        user = await user_svc.authenticate_user(current_user["email"], request.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="รหัสผ่านไม่ถูกต้อง"
            )
        
        # ปิดการใช้งาน
        success = await totp_svc.disable_totp(current_user["id"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถปิดใช้งาน TOTP ได้"
            )
            
        # Audit Log (ไม่ให้ audit error หยุดการทำงานหลัก)
        try:
            await audit_svc.create_audit_log(
                actor_user_id=current_user["id"],
                action="DISABLE_TOTP",
                details={"method": "TOTP"}
            )
        except Exception as audit_error:
            print(f"Error creating audit log: {audit_error}")
            # ไม่ให้ audit error หยุดการทำงานหลัก
        
        return {"message": "ปิดใช้งาน TOTP เรียบร้อยแล้ว"}
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = f"Error in disable_totp endpoint: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        print(error_detail)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการปิดใช้งาน TOTP: {str(e)}"
        )
