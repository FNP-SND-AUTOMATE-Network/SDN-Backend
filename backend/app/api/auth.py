from fastapi import APIRouter, HTTPException, status, Request, Response
from app.models.auth import (
    RegisterRequest, RegisterResponse, VerifyOtpRequest, VerifyOtpResponse, 
    ResendOtpRequest, ResendOtpResponse, LoginRequest, LoginResponse, ErrorResponse,
    TotpSetupResponse, TotpVerifyRequest, TotpDisableRequest, VerifyTotpLoginRequest,
    ForgotPasswordRequest, ForgotPasswordResponse, ResetPasswordRequest, ResetPasswordResponse,
    UserAuthMeResponse
)
from app.services.otp_service import OtpService
from app.services.user_service import UserService
from app.services.audit_service import AuditService
from app.services.totp_service import TotpService
from datetime import datetime, timezone, timedelta
from app.api.users import get_current_user
from fastapi import Depends, Cookie
from app.core.config import settings as app_settings
from app.core.csrf import generate_csrf_token
from app.core.logging import logger
from app.utils.request_helpers import get_client_ip, get_user_agent

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
    try:
        # Get initialized services
        otp_svc, user_svc, audit_svc, _ = get_services()
        
        #ตรวจสอบว่า email มีอยู่ในระบบแล้วหรือไม่
        email_exists = await user_svc.check_email_exists(request.email)
        if email_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists"
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
        
        try:
            # สร้าง OTP
            otp_code, expires_at = await otp_svc.create_otp_record(request.email)
            
            # ส่ง OTP ผ่านอีเมล
            email_sent = await otp_svc.send_otp_email(request.email, otp_code, request.name, request.surname)
            
            if not email_sent:
                raise Exception("Email sending service returned False")
                
        except Exception as e:
            # Rollback: ลบ user ที่เพิ่งสร้างถ้าส่ง OTP ไม่สำเร็จ
            await prisma_client.user.delete(where={"id": temp_user.id})
            logger.error(f"Failed to send OTP during registration: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send OTP. Please try again."
            )
        
        return RegisterResponse(
            message="OTP sent to your email. Please check your email and confirm your registration.",
            email=request.email,
            expires_at=expires_at
        )
        
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send OTP. Please try again."
        )


@router.post("/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp(request: VerifyOtpRequest, req: Request):
    try:
        # Get initialized services
        otp_svc, user_svc, audit_svc, _ = get_services()
        
        #ตรวจสอบ OTP
        user_id = await otp_svc.verify_otp(request.email, request.otp_code)
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OTP code. Please try again."
            )
        
        # ดึงข้อมูล user ที่สร้างไว้ชั่วคราว
        temp_user = await user_svc.get_user_by_email(request.email)
        
        if not temp_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User not found. Please register again."
            )
        
        # อัปเดตสถานะ emailVerified เป็น True ใช้ global client
        prisma_client = get_prisma_client()
        updated_user = await prisma_client.user.update(
            where={"id": user_id},
            data={"emailVerified": True}
        )
        
        # สร้าง audit log สำหรับการสมัครสมาชิกสำเร็จ
        try:
            client_ip = get_client_ip(req)
            user_agent = get_user_agent(req)
            
            await audit_svc.create_register_audit(
                user_id=updated_user.id,
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as audit_error:
            logger.warning(f"Error creating register audit log: {audit_error}")
            # ไม่ให้ audit error หยุดการทำงานหลัก
        
        return VerifyOtpResponse(
            message="OTP verified successfully",
            user_id=updated_user.id,
            email=updated_user.email,
            email_verified=True
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in verify_otp: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during OTP verification."
        )


@router.post("/resend-otp", response_model=ResendOtpResponse)
async def resend_otp(request: ResendOtpRequest):
    try:
        # Get initialized services
        otp_svc, user_svc, audit_svc, _ = get_services()
        
        #ตรวจสอบว่า email มีอยู่ในระบบและยังไม่ได้ยืนยัน
        user = await user_svc.get_user_by_email(request.email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User not found. Please register again."
            )
        
        if user["emailVerified"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already verified"
            )
        
        # สร้าง OTP ใหม่
        otp_code, expires_at = await otp_svc.create_otp_record(request.email)
        
        # ส่ง OTP ผ่านอีเมล (ใช้ name และ surname จาก database)
        email_sent = await otp_svc.send_otp_email(request.email, otp_code, user["name"] or "", user["surname"] or "")
        
        if not email_sent:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error in send_otp_email"
            )
        
        return ResendOtpResponse(
            message="OTP sent to your email. Please check your email and confirm your registration.",
            email=request.email,
            expires_at=expires_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in resend_otp: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while resending OTP."
        )


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, req: Request, response: Response):
    try:
        # Get initialized services
        otp_svc, user_svc, audit_svc, totp_svc = get_services()
        
        #ตรวจสอบข้อมูลผู้ใช้และรหัสผ่าน
        user = await user_svc.authenticate_user(request.email, request.password)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        #ตรวจสอบว่ามีการเปิดใช้งาน TOTP หรือไม่
        totp_secret = await totp_svc.get_user_totp_secret(user["id"])
        
        if totp_secret:
            # สร้าง temporary token สำหรับยืนยัน TOTP
            temp_token_data = {
                "sub": user["id"],
                "user_id": user["id"],
                "email": user["email"],
                "totp_required": True,
                "exp": datetime.now(timezone.utc).timestamp() + 300  # หมดอายุใน 5 นาที
            }
            temp_token = user_svc.create_access_token(temp_token_data)
            
            return LoginResponse(
                message="Please verify TOTP code",
                user_id=user["id"],
                email=user["email"],
                name=user["name"],
                surname=user["surname"],
                role=user["role"],
                requires_totp=True,
                temp_token=temp_token
            )
        
        #ถ้าไม่ต้องใช้ TOTP สร้าง access token ปกติ
        access_token_data = {
            "sub": user["id"],  #ใช้ user_id แทน email สำหรับ JWT sub
            "user_id": user["id"],
            "role": user["role"]
        }
        access_token = user_svc.create_access_token(access_token_data)
        refresh_token = user_svc.create_refresh_token(access_token_data)
        
        # ตั้งค่า HttpOnly Cookies สำหรับ access token และ refresh token
        _secure = app_settings.SECURE_COOKIES
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=_secure,
            samesite="lax",
            max_age=user_svc.access_token_expire_minutes * 60
        )
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=_secure,
            samesite="lax",
            max_age=7 * 24 * 60 * 60 # 7 วัน
        )
        # CSRF token — readable by JS (not HttpOnly) so frontend can attach it as X-CSRF-Token header
        csrf_token = generate_csrf_token()
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,   # intentionally readable by JS
            secure=_secure,
            samesite="strict",
            max_age=user_svc.access_token_expire_minutes * 60
        )
        
        #สร้าง audit log สำหรับการ login สำเร็จ
        try:
            client_ip = get_client_ip(req)
            user_agent = get_user_agent(req)
            
            await audit_svc.create_login_audit(
                user_id=user["id"],
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as audit_error:
            logger.warning(f"Error creating login audit log: {audit_error}")
            #ไม่ให้ audit error หยุดการทำงานหลัก
        
        return LoginResponse(
            message="Login successful",
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
        logger.error(f"Error in login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during login."
        )


# ========= MFA / TOTP Endpoints =========

@router.post("/mfa/setup", response_model=TotpSetupResponse)
async def setup_totp(
    current_user: dict = Depends(get_current_user)
):
    try:
        _, _, _, totp_svc = get_services()
        
        #สร้าง Secret ใหม่
        secret = totp_svc.generate_secret()
        
        #สร้าง URL สำหรับ QR Code
        provisioning_uri = totp_svc.get_provisioning_uri(secret, current_user["email"])
        
        return TotpSetupResponse(
            secret=secret,
            provisioning_uri=provisioning_uri
        )
        
    except Exception as e:
        logger.error(f"Error in setup_totp: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during TOTP setup."
        )


@router.post("/mfa/verify", response_model=dict)
async def verify_totp_setup(
    request: TotpVerifyRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        #Validate request data
        if not request.secret or not request.otp_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid request data"
            )
        
        _, _, audit_svc, totp_svc = get_services()
        
        # ตรวจสอบรหัส TOTP
        is_valid = totp_svc.verify_totp(request.secret, request.otp_code)
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid TOTP code"
            )
        
        # บันทึกและเปิดใช้งาน TOTP
        success = await totp_svc.enable_totp(current_user["id"], request.secret)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error in enable_totp"
            )
            
        # Audit Log
        try:
            await audit_svc.create_audit_log(
                actor_user_id=current_user["id"],
                action="ENABLE_TOTP",
                details={"method": "TOTP"}
            )
        except Exception as audit_error:
            logger.warning(f"Error creating audit log: {audit_error}")
            # ไม่ให้ audit error หยุดการทำงานหลัก
        
        return {"message": "TOTP enabled successfully"}
        
    except HTTPException:
        raise
    except ValueError as e:
        # Handle validation errors from Pydantic
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid request data: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error in verify_totp_setup: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during TOTP setup verification."
        )




@router.post("/mfa-verify-totp-login", response_model=LoginResponse)
async def verify_totp_login(request: VerifyTotpLoginRequest, response: Response):
    try:
        logger.debug("Verifying TOTP login")
        #Get initialized services
        _, user_svc, audit_svc, totp_svc = get_services()
        
        #ตรวจสอบ temp token
        try:
            token_data = user_svc.verify_token(request.temp_token)
            
            if not token_data.get("totp_required"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Token is invalid or does not support TOTP verification"
                )
            
            user_id = token_data.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid Token"
                )
            
            #ดึงข้อมูลผู้ใช้
            user = await user_svc.get_user_by_id(user_id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            # ดึง TOTP secret
            totp_secret = await totp_svc.get_user_totp_secret(user_id)
            if not totp_secret:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="TOTP not found"
                )
            
            # ตรวจสอบรหัส TOTP
            is_valid = totp_svc.verify_totp(totp_secret, request.otp_code)
            
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="2FA 6-digit code expired or incorrect, please try again"
                )
            
            # สร้าง access token จริง
            access_token_data = {
                "sub": user["id"],
                "user_id": user["id"],
                "role": user["role"]
            }
            access_token = user_svc.create_access_token(access_token_data)
            refresh_token = user_svc.create_refresh_token(access_token_data)
            
            # ตั้งค่า HttpOnly Cookies
            _secure = app_settings.SECURE_COOKIES
            response.set_cookie(
                key="access_token",
                value=access_token,
                httponly=True,
                secure=_secure,
                samesite="lax",
                max_age=user_svc.access_token_expire_minutes * 60
            )
            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                httponly=True,
                secure=_secure,
                samesite="lax",
                max_age=7 * 24 * 60 * 60 # 7 days
            )
            # CSRF token — readable by JS
            csrf_token = generate_csrf_token()
            response.set_cookie(
                key="csrf_token",
                value=csrf_token,
                httponly=False,
                secure=_secure,
                samesite="strict",
                max_age=user_svc.access_token_expire_minutes * 60
            )
            
            # Audit Log
            try:
                await audit_svc.create_audit_log(
                    actor_user_id=user["id"],
                    action="LOGIN_WITH_TOTP",
                    details={"method": "TOTP", "status": "success"}
                )
            except Exception as audit_error:
                logger.warning(f"Error creating audit log: {audit_error}")
            
            logger.debug("TOTP login successful")
            return LoginResponse(
                message="Login successful",
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
            logger.error(f"Token verification error in TOTP login: {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired or invalid"
            )

            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in verify_totp_login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during TOTP verification."
        )


@router.post("/mfa/disable", response_model=dict)
async def disable_totp(
    request: TotpDisableRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        logger.debug("Disable TOTP request received")
        _, user_svc, audit_svc, totp_svc = get_services()
        
        #ตรวจสอบรหัสผ่านเพื่อความปลอดภัย
        user = await user_svc.authenticate_user(current_user["email"], request.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password"
            )
        
        # ปิดการใช้งาน
        success = await totp_svc.disable_totp(current_user["id"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error in disable_totp"
            )
            
        # Audit Log (ไม่ให้ audit error หยุดการทำงานหลัก)
        try:
            await audit_svc.create_audit_log(
                actor_user_id=current_user["id"],
                action="DISABLE_TOTP",
                details={"method": "TOTP"}
            )
        except Exception as audit_error:
            logger.warning(f"Error creating audit log: {audit_error}")
            # ไม่ให้ audit error หยุดการทำงานหลัก
        
        return {"message": "2FA disabled successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in disable_totp endpoint: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while disabling TOTP."
        )


# ========= Forgot Password Endpoints =========

@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(request: ForgotPasswordRequest):
    try:
        otp_svc, user_svc, audit_svc, _ = get_services()
        
        # Always return a consistent response to prevent email enumeration
        generic_response = ForgotPasswordResponse(
            message="If an account with this email exists, a password reset OTP has been sent.",
            email=request.email,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
        )
        
        # ตรวจสอบว่า email มีอยู่ในระบบหรือไม่
        user = await user_svc.get_user_by_email(request.email)
        if not user:
            # Return generic response to prevent email enumeration (Finding #6)
            return generic_response
        
        # สร้าง OTP สำหรับรีเซ็ตรหัสผ่าน
        try:
            otp_code, expires_at = await otp_svc.create_otp_record(
                request.email, 
                purpose="RESET_PASSWORD"
            )
            
            # ส่ง OTP ผ่านอีเมล
            email_sent = await otp_svc.send_otp_email(
                request.email, 
                otp_code, 
                user.get("name", ""), 
                user.get("surname", ""),
                purpose="RESET_PASSWORD"
            )
            
            if not email_sent:
                logger.error(f"Failed to send password reset email to {request.email}")
        except Exception as send_error:
            logger.error(f"Error in forgot_password OTP flow: {send_error}")
        
        # Audit Log
        try:
            await audit_svc.create_audit_log(
                actor_user_id=user["id"],
                action="PASSWORD_RESET",
                details={"step": "request", "email": request.email}
            )
        except Exception as audit_error:
            logger.warning(f"Error creating audit log: {audit_error}")
        
        return generic_response
        
    except Exception as e:
        logger.error(f"Error in forgot_password: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred."
        )


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(request: ResetPasswordRequest):
    try:
        otp_svc, user_svc, audit_svc, _ = get_services()
        
        # ตรวจสอบ OTP
        user_id = await otp_svc.verify_otp(
            request.email, 
            request.otp_code, 
            purpose="RESET_PASSWORD"
        )
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP code"
            )
        
        # ดึงข้อมูล user
        user = await user_svc.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # เข้ารหัสรหัสผ่านใหม่
        new_hashed_password = user_svc.hash_password(request.new_password)
        
        # อัปเดตรหัสผ่าน
        prisma_client = get_prisma_client()
        await prisma_client.user.update(
            where={"id": user_id},
            data={
                "password": new_hashed_password,
                "updatedAt": datetime.now(timezone.utc)
            }
        )
        
        # ลบ OTP ที่เกี่ยวข้องทั้งหมด (ป้องกันการใช้ซ้ำ)
        await prisma_client.emailotp.delete_many(
            where={
                "userId": user_id,
                "purpose": "RESET_PASSWORD"
            }
        )
        
        # Audit Log
        try:
            await audit_svc.create_audit_log(
                actor_user_id=user_id,
                action="PASSWORD_RESET",
                details={"step": "completed", "email": request.email}
            )
        except Exception as audit_error:
            logger.warning(f"Error creating audit log: {audit_error}")
        
        return ResetPasswordResponse(
            message="Password reset successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in reset_password: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during password reset."
        )


# ========= Session endpoints (HTTP-Only Cookie Management) =========

@router.get("/me", response_model=UserAuthMeResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    user_svc = get_services()[1]
    user_detail = await user_svc.get_user_detail_by_id(current_user["id"])
    if not user_detail:
        raise HTTPException(status_code=404, detail="User not found")
        
    return UserAuthMeResponse(
        id=user_detail["id"],
        email=user_detail["email"],
        name=user_detail["name"],
        surname=user_detail["surname"],
        role=user_detail["role"],
        has_strong_mfa=user_detail["has_strong_mfa"],
        totp_enabled=user_detail["totp_enabled"]
    )

@router.post("/refresh")
async def refresh_token(request: Request, response: Response):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")
    try:
        user_svc = get_services()[1]
        user_id = await user_svc.verify_refresh_token(refresh_token)
        user = await user_svc.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
        
        access_token_data = {"sub": user["id"], "user_id": user["id"], "role": user["role"]}
        access_token = user_svc.create_access_token(access_token_data)
        new_refresh_token = user_svc.create_refresh_token(access_token_data)
        
        _secure = app_settings.SECURE_COOKIES
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=_secure,
            samesite="lax",
            max_age=user_svc.access_token_expire_minutes * 60
        )
        response.set_cookie(
            key="refresh_token",
            value=new_refresh_token,
            httponly=True,
            secure=_secure,
            samesite="lax",
            max_age=7 * 24 * 60 * 60
        )
        # Rotate CSRF token on every refresh
        csrf_token = generate_csrf_token()
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,
            secure=_secure,
            samesite="strict",
            max_age=user_svc.access_token_expire_minutes * 60
        )
        
        return {"message": "Tokens refreshed"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

@router.post("/logout")
async def logout(response: Response):
    _secure = app_settings.SECURE_COOKIES
    response.delete_cookie(key="access_token", samesite="lax", secure=_secure)
    response.delete_cookie(key="refresh_token", samesite="lax", secure=_secure)
    response.delete_cookie(key="csrf_token", samesite="strict", secure=_secure)
    return {"message": "Logout successful"}
