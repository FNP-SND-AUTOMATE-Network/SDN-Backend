from fastapi import APIRouter, HTTPException, status, Depends, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, List, Callable
from app.models.user import (
    UserCreateRequest, UserUpdateRequest, UserChangePasswordRequest,
    UserResponse, UserDetailResponse, UserListResponse, 
    UserCreateResponse, UserUpdateResponse, UserDeleteResponse, PasswordChangeResponse,
    UserFilter, UserRole, ErrorResponse
)
from app.services.user_service import UserService
from app.services.audit_service import AuditService
from app.database import get_prisma_client, is_prisma_client_ready
from app.utils.role_hierarchy import RoleHierarchy
from app.utils.request_helpers import get_client_ip, get_user_agent
from app.core.logging import logger

router = APIRouter(prefix="/users", tags=["User Management"])

# Security
security = HTTPBearer(auto_error=False)

# Services จะได้รับ prisma client ใน runtime
user_service = None
audit_service = None

def get_services():
    global user_service, audit_service
    
    # Initialize services if not already done
    if user_service is None or audit_service is None:
        if not is_prisma_client_ready():
            raise HTTPException(
                status_code=500,
                detail="Database connection not ready. Please try again."
            )
        
        prisma_client = get_prisma_client()
        user_service = UserService(prisma_client)
        audit_service = AuditService(prisma_client)
    
    return user_service, audit_service

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    try:
        user_svc, audit_svc = get_services()
        
        # Try to get token from cookie first
        token = request.cookies.get("access_token")
        
        # Fallback to Authorization Header (Bearer token)
        if not token and credentials:
            token = credentials.credentials
            
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated"
            )
            
        user_id = await user_svc.verify_access_token(token)
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        
        user = await user_svc.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        return user
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal authentication error occurred."
        )

def verify_role(allowed_roles: List[str]) -> Callable:
    def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Requires one of: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker

def check_admin_permission(current_user: dict):
    if current_user.get("role") not in ["ADMIN", "OWNER"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required"
        )

def check_engineer_permission(current_user: dict):
    if current_user.get("role") not in ["ENGINEER", "ADMIN", "OWNER"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Engineer or Admin permission required"
        )

def check_admin_or_self_permission(current_user: dict, target_user_id: str):
    if current_user["role"] not in ["ADMIN", "OWNER"] and current_user["id"] != target_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this"
        )

# ========= User CRUD Endpoints =========

@router.post("/", response_model=UserCreateResponse)
async def create_user(
    request: UserCreateRequest,
    current_user: dict = Depends(get_current_user),
    req: Request = None
):
    try:
        # ตรวจสอบสิทธิ์ admin
        check_admin_permission(current_user)
        
        # ตรวจสอบว่าสามารถสร้าง user ด้วย role ที่ระบุได้หรือไม่
        if not RoleHierarchy.can_create_user_with_role(current_user["role"], request.role.value):
            allowed_roles = RoleHierarchy.get_allowed_creation_roles(current_user["role"])
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have permission to create a user with role '{request.role.value}'. Allowed roles: {', '.join(allowed_roles)}"
            )
        
        user_svc, audit_svc = get_services()
        
        # ดึง OTP service
        from app.services.otp_service import OtpService
        prisma_client = get_prisma_client()
        otp_svc = OtpService(prisma_client)
        
        # สร้าง user ใหม่พร้อม OTP
        new_user = await user_svc.create_user_by_admin(request, otp_svc)
        
        # สร้าง audit log
        try:
            client_ip = get_client_ip(req)
            user_agent = get_user_agent(req)
            
            await audit_svc.create_user_create_audit(
                actor_user_id=current_user["id"],
                target_user_id=new_user["id"],
                target_email=new_user["email"],
                target_role=new_user.get("target_role", "VIEWER"),
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as audit_error:
            logger.warning(f"Error creating audit log: {audit_error}")
        
        # สร้าง response message ตามสถานะ
        if new_user.get("requires_otp_verification"):
            message = f"สร้างผู้ใช้งานใหม่เรียบร้อยแล้ว กรุณายืนยัน OTP ที่ส่งไปยัง {new_user['email']} เพื่อเปลี่ยน role เป็น {new_user.get('target_role', 'VIEWER')}"
        else:
            message = "สร้างผู้ใช้งานใหม่เรียบร้อยแล้ว"
        
        # สร้าง user response (ลบ fields พิเศษออก)
        user_data = {k: v for k, v in new_user.items() if k not in ['target_role', 'otp_expires_at', 'requires_otp_verification']}
        
        return UserCreateResponse(
            message=message,
            user=UserResponse(**user_data),
            target_role=new_user.get('target_role'),
            otp_expires_at=new_user.get('otp_expires_at'),
            requires_otp_verification=new_user.get('requires_otp_verification', False)
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while creating user."
        )

@router.get("/", response_model=UserListResponse)
async def get_users(
    page: int = Query(1, ge=1, description="หมายเลขหน้า"),
    page_size: int = Query(10, ge=1, le=100, description="จำนวนรายการต่อหน้า"),
    email: Optional[str] = Query(None, description="กรองตาม email"),
    name: Optional[str] = Query(None, description="กรองตาม name"),
    surname: Optional[str] = Query(None, description="กรองตาม surname"),
    role: Optional[UserRole] = Query(None, description="กรองตาม role"),
    email_verified: Optional[bool] = Query(None, description="กรองตามสถานะ email verification"),
    has_strong_mfa: Optional[bool] = Query(None, description="กรองตาม MFA status"),
    search: Optional[str] = Query(None, description="ค้นหาใน email, name, surname"),
    current_user: dict = Depends(get_current_user)
):
    try:
        # ตรวจสอบสิทธิ์ admin
        check_admin_permission(current_user)
        
        user_svc, audit_svc = get_services()
        
        # สร้าง filter object
        filters = UserFilter(
            email=email,
            name=name,
            surname=surname,
            role=role,
            email_verified=email_verified,
            has_strong_mfa=has_strong_mfa,
            search=search
        )
        
        # ดึงรายการ users
        users_data = await user_svc.get_users_list(page, page_size, filters)
        
        # แปลงเป็น UserResponse objects
        users_list = [UserResponse(**user) for user in users_data["users"]]
        
        # สร้าง audit log สำหรับการดูรายการ users
        try:
            from fastapi import Request
            
            # ดึง IP และ User Agent (ถ้าไม่มี req parameter ให้ใช้ค่า default)
            client_ip = "unknown"
            user_agent = "unknown"
            
            # สร้าง filters dict สำหรับ audit
            audit_filters = {
                "page": page,
                "page_size": page_size,
                "email": email,
                "name": name,
                "surname": surname,
                "role": role.value if role else None,
                "email_verified": email_verified,
                "has_strong_mfa": has_strong_mfa,
                "search": search
            }
            # ลบ None values
            audit_filters = {k: v for k, v in audit_filters.items() if v is not None}
            
            # Note: ไม่ทำ audit log สำหรับการดู user list เพราะไม่จำเป็น
            pass
        except Exception as audit_error:
            logger.warning(f"Error creating audit log: {audit_error}")
        
        return UserListResponse(
            users=users_list,
            total=users_data["total"],
            page=users_data["page"],
            page_size=users_data["page_size"],
            total_pages=users_data["total_pages"]
        )
        
    except Exception as e:
        logger.error(f"Error fetching user list: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while fetching user list."
        )

@router.get("/{user_id}", response_model=UserDetailResponse)
async def get_user_by_id(
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        # ตรวจสอบสิทธิ์
        check_admin_or_self_permission(current_user, user_id)
        
        user_svc, audit_svc = get_services()
        
        # ดึงข้อมูล user
        user = await user_svc.get_user_detail_by_id(user_id)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Note: ไม่ทำ audit log สำหรับการดู user detail เพราะไม่จำเป็น
        
        return UserDetailResponse(**user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while fetching user details."
        )

@router.put("/{user_id}", response_model=UserUpdateResponse)
async def update_user(
    user_id: str,
    request: UserUpdateRequest,
    current_user: dict = Depends(get_current_user),
    req: Request = None
):
    try:
        # ตรวจสอบสิทธิ์พื้นฐาน
        check_admin_or_self_permission(current_user, user_id)
        
        # ตรวจสอบสิทธิ์เฉพาะสำหรับการเปลี่ยน role
        if request.role:
            if current_user["role"] not in ["ADMIN", "OWNER"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to change role"
                )
            
            # ตรวจสอบ role hierarchy
            if not RoleHierarchy.can_promote_to_role(current_user["role"], request.role.value):
                allowed_roles = RoleHierarchy.get_allowed_promotion_roles(current_user["role"])
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"You do not have permission to change role to {request.role.value}. You can only promote to: {', '.join(allowed_roles)}"
                )
        
        user_svc, audit_svc = get_services()
        
        # อัปเดต user
        updated_user = await user_svc.update_user_by_id(user_id, request)
        
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # สร้าง audit log
        try:
            client_ip = get_client_ip(req)
            user_agent = get_user_agent(req)
            
            # สร้างรายละเอียดการเปลี่ยนแปลง
            changes = {}
            if request.email:
                changes["email"] = request.email
            if request.name is not None:
                changes["name"] = request.name
            if request.surname is not None:
                changes["surname"] = request.surname
            if request.role:
                changes["role"] = request.role.value
            if request.email_verified is not None:
                changes["email_verified"] = request.email_verified
            if request.has_strong_mfa is not None:
                changes["has_strong_mfa"] = request.has_strong_mfa
            
            await audit_svc.create_user_update_audit(
                actor_user_id=current_user["id"],
                target_user_id=user_id,
                changes=changes,
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as audit_error:
            logger.warning(f"Error creating audit log: {audit_error}")
        
        return UserUpdateResponse(
            message="User updated successfully",
            user=UserResponse(**updated_user)
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while updating user."
        )

@router.delete("/{user_id}", response_model=UserDeleteResponse)
async def delete_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    req: Request = None
):
    try:
        # ตรวจสอบสิทธิ์ admin
        check_admin_permission(current_user)
        
        # ป้องกันการลบตัวเอง
        if current_user["id"] == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot delete your own account"
            )
        
        user_svc, audit_svc = get_services()
        
        # ดึงข้อมูล user ก่อนลบ (สำหรับ audit)
        target_user = await user_svc.get_user_by_id(user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # สร้าง audit log ก่อนลบ user
        try:
            client_ip = get_client_ip(req)
            user_agent = get_user_agent(req)
            
            await audit_svc.create_user_delete_audit(
                actor_user_id=current_user["id"],
                target_user_id=user_id,
                target_email=target_user["email"],
                target_role=target_user["role"],
                ip_address=client_ip,
                user_agent=user_agent,
                actor_email=current_user["email"],
                actor_name=f"{current_user.get('name', '')} {current_user.get('surname', '')}".strip()
            )
        except Exception as audit_error:
            logger.warning(f"Error creating audit log: {audit_error}")
        
        # ลบ user
        success = await user_svc.delete_user_by_id(user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error deleting user"
            )
        
        return UserDeleteResponse(
            message="User deleted successfully",
            user_id=user_id
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while deleting user."
        )

# ========= Password Management Endpoints =========

@router.post("/{user_id}/change-password", response_model=PasswordChangeResponse)
async def change_password(
    user_id: str,
    request: UserChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    req: Request = None
):
    try:
        # ตรวจสอบว่าเป็น user เดียวกัน
        if current_user["id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot change password for another user"
            )
        
        user_svc, audit_svc = get_services()
        
        # เปลี่ยนรหัสผ่าน
        success = await user_svc.change_user_password(
            user_id, 
            request.current_password, 
            request.new_password
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error changing password"
            )
        
        # สร้าง audit log
        try:
            client_ip = get_client_ip(req)
            user_agent = get_user_agent(req)
            
            await audit_svc.create_password_change_audit(
                actor_user_id=current_user["id"],
                target_user_id=user_id,
                change_type="self",
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as audit_error:
            logger.warning(f"Error creating audit log: {audit_error}")
        
        return PasswordChangeResponse(
            message="Password changed successfully",
            user_id=user_id
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error changing password: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while changing password."
        )


# ========= Profile Endpoints =========

@router.get("/profile/me", response_model=UserDetailResponse)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    try:
        user_svc, audit_svc = get_services()
        
        # ดึงข้อมูลรายละเอียด user
        user = await user_svc.get_user_detail_by_id(current_user["id"])
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Note: ไม่ทำ audit log สำหรับการดู profile เพราะไม่จำเป็น
        
        return UserDetailResponse(**user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while fetching profile."
        )

@router.post("/{user_id}/promote-role", response_model=UserUpdateResponse)
async def promote_user_role(
    user_id: str,
    target_role: UserRole,
    current_user: dict = Depends(get_current_user),
    req: Request = None
):
    try:
        # ตรวจสอบสิทธิ์ admin
        check_admin_permission(current_user)
        
        # ตรวจสอบ role hierarchy
        if not RoleHierarchy.can_promote_to_role(current_user["role"], target_role.value):
            allowed_roles = RoleHierarchy.get_allowed_promotion_roles(current_user["role"])
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have permission to promote to role {target_role.value}. You can only promote to: {', '.join(allowed_roles)}"
            )
        
        user_svc, audit_svc = get_services()
        
        # ดึงข้อมูล user เก่าก่อนทำการ promote
        old_user = await user_svc.get_user_by_id(user_id)
        if not old_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        old_role = old_user["role"]
        
        # เปลี่ยน role
        updated_user = await user_svc.promote_user_role_after_verification(user_id, target_role.value)
        
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error promoting user role"
            )
        
        # สร้าง audit log
        try:
            client_ip = get_client_ip(req)
            user_agent = get_user_agent(req)
            
            await audit_svc.create_role_promotion_audit(
                actor_user_id=current_user["id"],
                target_user_id=user_id,
                old_role=old_role,
                new_role=target_role.value,
                promotion_type="after_verification",
                ip_address=client_ip,
                user_agent=user_agent
            )
        except Exception as audit_error:
            logger.warning(f"Error creating audit log: {audit_error}")
        
        return UserUpdateResponse(
            message=f"Promote user role to {target_role.value} successfully",
            user=UserResponse(**updated_user)
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error promoting user role: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while promoting user role."
        )
