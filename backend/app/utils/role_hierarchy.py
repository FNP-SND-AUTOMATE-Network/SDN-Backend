from typing import List, Dict
from enum import Enum

class UserRole(str, Enum):
    VIEWER = "VIEWER"
    ENGINEER = "ENGINEER" 
    ADMIN = "ADMIN"
    OWNER = "OWNER"

class RoleHierarchy:
    """
    ระบบ Role Hierarchy สำหรับควบคุมสิทธิ์การ promote และ create users
    
    Role Hierarchy (จากต่ำไปสูง):
    VIEWER < ENGINEER < ADMIN < OWNER
    
    กฎการ Promote:
    - OWNER: สามารถ promote เป็น role ใดก็ได้ (รวม ADMIN)
    - ADMIN: สามารถ promote ได้แค่ VIEWER, ENGINEER (ไม่ใช่ ADMIN)
    - ENGINEER: สามารถ promote ได้แค่ VIEWER, ENGINEER
    - VIEWER: ไม่สามารถ promote ใครได้
    """
    
    # Role hierarchy levels (ยิ่งสูงยิ่งมีสิทธิ์มาก)
    ROLE_LEVELS = {
        UserRole.VIEWER: 1,
        UserRole.ENGINEER: 2,
        UserRole.ADMIN: 3,
        UserRole.OWNER: 4
    }
    
    # กำหนด roles ที่แต่ละ role สามารถ promote ได้
    PROMOTION_PERMISSIONS = {
        UserRole.OWNER: [UserRole.VIEWER, UserRole.ENGINEER, UserRole.ADMIN],  # OWNER สามารถ promote เป็น ADMIN ได้
        UserRole.ADMIN: [UserRole.VIEWER, UserRole.ENGINEER],  # ADMIN ไม่สามารถ promote เป็น ADMIN ได้
        UserRole.ENGINEER: [UserRole.VIEWER, UserRole.ENGINEER],  # ENGINEER promote ได้แค่ระดับเดียวกันหรือต่ำกว่า
        UserRole.VIEWER: []  # VIEWER ไม่สามารถ promote ใครได้
    }
    
    # กำหนด roles ที่แต่ละ role สามารถสร้าง user ได้
    CREATE_USER_PERMISSIONS = {
        UserRole.OWNER: [UserRole.VIEWER, UserRole.ENGINEER, UserRole.ADMIN],  # OWNER สร้าง user เป็น ADMIN ได้
        UserRole.ADMIN: [UserRole.VIEWER, UserRole.ENGINEER],  # ADMIN ไม่สามารถสร้าง user เป็น ADMIN ได้
        UserRole.ENGINEER: [UserRole.VIEWER, UserRole.ENGINEER],  # ENGINEER สร้างได้แค่ระดับเดียวกันหรือต่ำกว่า
        UserRole.VIEWER: []  # VIEWER ไม่สามารถสร้าง user ได้
    }
    
    @classmethod
    def get_role_level(cls, role: str) -> int:
        """ดึงระดับของ role"""
        try:
            return cls.ROLE_LEVELS[UserRole(role)]
        except (ValueError, KeyError):
            return 0  # role ไม่ถูกต้อง
    
    @classmethod
    def can_promote_to_role(cls, actor_role: str, target_role: str) -> bool:
        """ตรวจสอบว่า actor_role สามารถ promote คนอื่นเป็น target_role ได้หรือไม่"""
        try:
            actor_role_enum = UserRole(actor_role)
            target_role_enum = UserRole(target_role)
            
            # ตรวจสอบว่า target_role อยู่ในรายการที่ actor_role สามารถ promote ได้หรือไม่
            allowed_roles = cls.PROMOTION_PERMISSIONS.get(actor_role_enum, [])
            return target_role_enum in allowed_roles
            
        except (ValueError, KeyError):
            return False
    
    @classmethod
    def can_create_user_with_role(cls, actor_role: str, target_role: str) -> bool:
        """ตรวจสอบว่า actor_role สามารถสร้าง user ด้วย target_role ได้หรือไม่"""
        try:
            actor_role_enum = UserRole(actor_role)
            target_role_enum = UserRole(target_role)
            
            # ตรวจสอบว่า target_role อยู่ในรายการที่ actor_role สามารถสร้างได้หรือไม่
            allowed_roles = cls.CREATE_USER_PERMISSIONS.get(actor_role_enum, [])
            return target_role_enum in allowed_roles
            
        except (ValueError, KeyError):
            return False
    
    @classmethod
    def get_allowed_promotion_roles(cls, actor_role: str) -> List[str]:
        """ดึงรายการ roles ที่ actor_role สามารถ promote ได้"""
        try:
            actor_role_enum = UserRole(actor_role)
            allowed_roles = cls.PROMOTION_PERMISSIONS.get(actor_role_enum, [])
            return [role.value for role in allowed_roles]
        except (ValueError, KeyError):
            return []
    
    @classmethod
    def get_allowed_creation_roles(cls, actor_role: str) -> List[str]:
        """ดึงรายการ roles ที่ actor_role สามารถสร้าง user ได้"""
        try:
            actor_role_enum = UserRole(actor_role)
            allowed_roles = cls.CREATE_USER_PERMISSIONS.get(actor_role_enum, [])
            return [role.value for role in allowed_roles]
        except (ValueError, KeyError):
            return []
    
    @classmethod
    def is_higher_role(cls, role1: str, role2: str) -> bool:
        """ตรวจสอบว่า role1 มีระดับสูงกว่า role2 หรือไม่"""
        return cls.get_role_level(role1) > cls.get_role_level(role2)
    
    @classmethod
    def is_same_or_lower_role(cls, role1: str, role2: str) -> bool:
        """ตรวจสอบว่า role1 มีระดับเท่ากันหรือต่ำกว่า role2 หรือไม่"""
        return cls.get_role_level(role1) <= cls.get_role_level(role2)
    
    @classmethod
    def get_role_description(cls, role: str) -> str:
        """ดึงคำอธิบายของ role"""
        descriptions = {
            UserRole.VIEWER: "ผู้ใช้ทั่วไป - ดูข้อมูลได้อย่างเดียว",
            UserRole.ENGINEER: "วิศวกร - จัดการข้อมูลและระบบได้",
            UserRole.ADMIN: "ผู้ดูแลระบบ - จัดการ users และระบบได้ (ยกเว้น ADMIN อื่น)",
            UserRole.OWNER: "เจ้าของระบบ - มีสิทธิ์เต็มในทุกอย่าง"
        }
        try:
            return descriptions[UserRole(role)]
        except (ValueError, KeyError):
            return "Role ไม่ถูกต้อง"
    
    @classmethod
    def validate_role_promotion(cls, actor_role: str, current_role: str, target_role: str) -> Dict[str, any]:
        """
        ตรวจสอบและให้ข้อมูลเกี่ยวกับการ promote role
        
        Returns:
        {
            "allowed": bool,
            "reason": str,
            "current_level": int,
            "target_level": int,
            "actor_permissions": List[str]
        }
        """
        result = {
            "allowed": False,
            "reason": "",
            "current_level": cls.get_role_level(current_role),
            "target_level": cls.get_role_level(target_role),
            "actor_permissions": cls.get_allowed_promotion_roles(actor_role)
        }
        
        # ตรวจสอบว่า role ทั้งหมดถูกต้องหรือไม่
        try:
            UserRole(actor_role)
            UserRole(current_role)
            UserRole(target_role)
        except ValueError as e:
            result["reason"] = f"Role ไม่ถูกต้อง: {str(e)}"
            return result
        
        # ตรวจสอบว่าไม่ใช่การ promote ตัวเอง
        if current_role == target_role:
            result["reason"] = "ไม่สามารถ promote เป็น role เดียวกันได้"
            return result
        
        # ตรวจสอบสิทธิ์ในการ promote
        if not cls.can_promote_to_role(actor_role, target_role):
            allowed_roles = cls.get_allowed_promotion_roles(actor_role)
            if not allowed_roles:
                result["reason"] = f"Role {actor_role} ไม่มีสิทธิ์ promote ใครได้"
            else:
                result["reason"] = f"Role {actor_role} สามารถ promote ได้เฉพาะ: {', '.join(allowed_roles)}"
            return result
        
        # ผ่านการตรวจสอบทั้งหมด
        result["allowed"] = True
        result["reason"] = f"สามารถ promote จาก {current_role} เป็น {target_role} ได้"
        
        return result