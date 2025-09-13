from typing import List, Optional, Dict, Any
from datetime import datetime
from app.models.audit import AuditLogCreate, AuditLogResponse, AuditLogFilter, AuditAction
import json


class AuditService:
    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def create_audit_log(self, audit_data: AuditLogCreate) -> AuditLogResponse:
        """สร้าง audit log ใหม่"""
        try:
            # แปลง details เป็น JSON หากมี
            details_json = None
            if audit_data.details:
                if isinstance(audit_data.details, dict):
                    details_json = json.dumps(audit_data.details, ensure_ascii=False)
                else:
                    details_json = str(audit_data.details)

            audit_log = await self.prisma.auditlog.create(
                data={
                    "actorUserId": audit_data.actor_user_id,
                    "targetUserId": audit_data.target_user_id,
                    "action": audit_data.action.value,
                    "details": details_json
                }
            )

            # แปลงกลับเป็น dict เพื่อ return
            return AuditLogResponse(
                id=audit_log.id,
                actor_user_id=audit_log.actorUserId,
                target_user_id=audit_log.targetUserId,
                action=audit_log.action,
                details=json.loads(audit_log.details) if audit_log.details else None,
                created_at=audit_log.createdAt
            )
        except Exception as e:
            print(f"Error creating audit log: {e}")
            raise e

    async def get_audit_logs(self, filters: AuditLogFilter) -> tuple[List[AuditLogResponse], int]:
        """ดึงรายการ audit logs ตาม filter"""
        try:
            # สร้าง where clause
            where_clause = {}
            
            if filters.actor_user_id:
                where_clause["actorUserId"] = filters.actor_user_id
            
            if filters.target_user_id:
                where_clause["targetUserId"] = filters.target_user_id
            
            if filters.action:
                where_clause["action"] = filters.action.value
            
            if filters.start_date or filters.end_date:
                date_filter = {}
                if filters.start_date:
                    date_filter["gte"] = filters.start_date
                if filters.end_date:
                    date_filter["lte"] = filters.end_date
                where_clause["createdAt"] = date_filter

            # ดึงข้อมูล (ไม่ใช้ include เพราะ Prisma Python มีข้อจำกัด)
            audit_logs = await self.prisma.auditlog.find_many(
                where=where_clause,
                skip=filters.offset,
                take=filters.limit,
                order={"createdAt": "desc"}
            )

            # นับจำนวนทั้งหมด
            total = await self.prisma.auditlog.count(where=where_clause)

            # แปลงเป็น response
            responses = []
            for audit_log in audit_logs:
                # เตรียม details
                details = None
                if audit_log.details:
                    try:
                        details = json.loads(audit_log.details)
                    except:
                        details = {"raw": audit_log.details}
                
                # เพิ่มข้อมูล actor และ target ลงใน details (ดึงแยก)
                if details is None:
                    details = {}
                
                if audit_log.actorUserId:
                    try:
                        actor_user = await self.prisma.user.find_unique(
                            where={"id": audit_log.actorUserId}
                        )
                        if actor_user:
                            details["actor_info"] = {
                                "id": actor_user.id,
                                "email": actor_user.email,
                                "name": actor_user.name,
                                "surname": actor_user.surname
                            }
                    except:
                        pass
                
                if audit_log.targetUserId:
                    try:
                        target_user = await self.prisma.user.find_unique(
                            where={"id": audit_log.targetUserId}
                        )
                        if target_user:
                            details["target_info"] = {
                                "id": target_user.id,
                                "email": target_user.email,
                                "name": target_user.name,
                                "surname": target_user.surname
                            }
                    except:
                        pass

                responses.append(AuditLogResponse(
                    id=audit_log.id,
                    actor_user_id=audit_log.actorUserId,
                    target_user_id=audit_log.targetUserId,
                    action=audit_log.action,
                    details=details,
                    created_at=audit_log.createdAt
                ))

            return responses, total

        except Exception as e:
            print(f"Error getting audit logs: {e}")
            raise e

    async def get_audit_log_by_id(self, audit_id: str) -> Optional[AuditLogResponse]:
        """ดึง audit log ตาม ID"""
        try:
            audit_log = await self.prisma.auditlog.find_unique(
                where={"id": audit_id}
            )

            if not audit_log:
                return None

            # เตรียม details
            details = None
            if audit_log.details:
                try:
                    details = json.loads(audit_log.details)
                except:
                    details = {"raw": audit_log.details}
            
            # เพิ่มข้อมูล actor และ target ลงใน details (ดึงแยก)
            if details is None:
                details = {}
            
            if audit_log.actorUserId:
                try:
                    actor_user = await self.prisma.user.find_unique(
                        where={"id": audit_log.actorUserId}
                    )
                    if actor_user:
                        details["actor_info"] = {
                            "id": actor_user.id,
                            "email": actor_user.email,
                            "name": actor_user.name,
                            "surname": actor_user.surname
                        }
                except:
                    pass
            
            if audit_log.targetUserId:
                try:
                    target_user = await self.prisma.user.find_unique(
                        where={"id": audit_log.targetUserId}
                    )
                    if target_user:
                        details["target_info"] = {
                            "id": target_user.id,
                            "email": target_user.email,
                            "name": target_user.name,
                            "surname": target_user.surname
                        }
                except:
                    pass

            return AuditLogResponse(
                id=audit_log.id,
                actor_user_id=audit_log.actorUserId,
                target_user_id=audit_log.targetUserId,
                action=audit_log.action,
                details=details,
                created_at=audit_log.createdAt
            )

        except Exception as e:
            print(f"Error getting audit log by ID: {e}")
            raise e

    async def create_login_audit(self, user_id: str, ip_address: str = None, user_agent: str = None):
        """สร้าง audit log สำหรับการ login"""
        details = {
            "event": "user_login",
            "timestamp": datetime.now().isoformat()
        }
        
        if ip_address:
            details["ip_address"] = ip_address
        
        if user_agent:
            details["user_agent"] = user_agent

        audit_data = AuditLogCreate(
            actor_user_id=user_id,
            target_user_id=user_id,
            action=AuditAction.USER_LOGIN,
            details=details
        )

        return await self.create_audit_log(audit_data)

    async def create_register_audit(self, user_id: str, ip_address: str = None, user_agent: str = None):
        """สร้าง audit log สำหรับการ register"""
        details = {
            "event": "user_register",
            "timestamp": datetime.now().isoformat()
        }
        
        if ip_address:
            details["ip_address"] = ip_address
        
        if user_agent:
            details["user_agent"] = user_agent

        audit_data = AuditLogCreate(
            actor_user_id=user_id,
            target_user_id=user_id,
            action=AuditAction.USER_REGISTER,
            details=details
        )

        return await self.create_audit_log(audit_data)

    async def create_logout_audit(self, user_id: str, ip_address: str = None, user_agent: str = None):
        """สร้าง audit log สำหรับการ logout"""
        details = {
            "event": "user_logout",
            "timestamp": datetime.now().isoformat()
        }
        
        if ip_address:
            details["ip_address"] = ip_address
        
        if user_agent:
            details["user_agent"] = user_agent

        audit_data = AuditLogCreate(
            actor_user_id=user_id,
            target_user_id=user_id,
            action=AuditAction.USER_LOGOUT,
            details=details
        )

        return await self.create_audit_log(audit_data)
    
    # ========= User Management Audit Functions =========
    
    async def create_user_create_audit(self, actor_user_id: str, target_user_id: str, target_email: str, 
                                      target_role: str, ip_address: str = None, user_agent: str = None) -> Optional[dict]:
        """สร้าง audit log สำหรับการสร้าง user ใหม่"""
        details = {
            "event": "user_create",
            "target_email": target_email,
            "target_role": target_role,
            "timestamp": datetime.now().isoformat(),
            "created_via": "admin_panel"
        }
        
        if ip_address:
            details["ip_address"] = ip_address
        
        if user_agent:
            details["user_agent"] = user_agent

        audit_data = AuditLogCreate(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=AuditAction.USER_CREATE,
            details=details
        )

        return await self.create_audit_log(audit_data)
    
    async def create_user_update_audit(self, actor_user_id: str, target_user_id: str, changes: dict,
                                      ip_address: str = None, user_agent: str = None) -> Optional[dict]:
        """สร้าง audit log สำหรับการอัปเดต user"""
        details = {
            "event": "user_update",
            "changes": changes,
            "timestamp": datetime.now().isoformat()
        }
        
        if ip_address:
            details["ip_address"] = ip_address
        
        if user_agent:
            details["user_agent"] = user_agent

        audit_data = AuditLogCreate(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=AuditAction.USER_UPDATE,
            details=details
        )

        return await self.create_audit_log(audit_data)
    
    async def create_user_delete_audit(self, actor_user_id: str, target_user_id: str, target_email: str,
                                      target_role: str, ip_address: str = None, user_agent: str = None, 
                                      actor_email: str = None, actor_name: str = None) -> Optional[dict]:
        """สร้าง audit log สำหรับการลบ user"""
        details = {
            "event": "user_delete",
            "target_email": target_email,
            "target_role": target_role,
            "deleted_by_user_id": actor_user_id,
            "deleted_by_email": actor_email,
            "deleted_by_name": actor_name,
            "timestamp": datetime.now().isoformat()
        }
        
        if ip_address:
            details["ip_address"] = ip_address
        
        if user_agent:
            details["user_agent"] = user_agent

        audit_data = AuditLogCreate(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=AuditAction.USER_DELETE,
            details=details
        )

        return await self.create_audit_log(audit_data)
    
    async def create_user_view_audit(self, actor_user_id: str, target_user_id: str, view_type: str = "detail",
                                    ip_address: str = None, user_agent: str = None) -> Optional[dict]:
        """สร้าง audit log สำหรับการดู user (เฉพาะกรณีที่สำคัญ)"""
        details = {
            "event": "user_view",
            "view_type": view_type,  # "detail", "profile", "list"
            "timestamp": datetime.now().isoformat()
        }
        
        if ip_address:
            details["ip_address"] = ip_address
        
        if user_agent:
            details["user_agent"] = user_agent

        audit_data = AuditLogCreate(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=AuditAction.USER_VIEW,
            details=details
        )

        return await self.create_audit_log(audit_data)
    
    async def create_user_list_audit(self, actor_user_id: str, filters: dict = None,
                                    ip_address: str = None, user_agent: str = None) -> Optional[dict]:
        """สร้าง audit log สำหรับการดูรายการ users"""
        details = {
            "event": "user_list",
            "filters": filters or {},
            "timestamp": datetime.now().isoformat()
        }
        
        if ip_address:
            details["ip_address"] = ip_address
        
        if user_agent:
            details["user_agent"] = user_agent

        audit_data = AuditLogCreate(
            actor_user_id=actor_user_id,
            target_user_id=None,  # list operation ไม่มี target specific
            action=AuditAction.USER_LIST,
            details=details
        )

        return await self.create_audit_log(audit_data)
    
    async def create_password_change_audit(self, actor_user_id: str, target_user_id: str, change_type: str = "self",
                                          ip_address: str = None, user_agent: str = None) -> Optional[dict]:
        """สร้าง audit log สำหรับการเปลี่ยนรหัสผ่าน"""
        details = {
            "event": "password_change",
            "change_type": change_type,  # "self", "admin_reset"
            "timestamp": datetime.now().isoformat()
        }
        
        if ip_address:
            details["ip_address"] = ip_address
        
        if user_agent:
            details["user_agent"] = user_agent

        audit_data = AuditLogCreate(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=AuditAction.PASSWORD_CHANGE if change_type == "self" else AuditAction.PASSWORD_RESET,
            details=details
        )

        return await self.create_audit_log(audit_data)
    
    async def create_role_promotion_audit(self, actor_user_id: str, target_user_id: str, old_role: str, 
                                         new_role: str, promotion_type: str = "manual",
                                         ip_address: str = None, user_agent: str = None) -> Optional[dict]:
        """สร้าง audit log สำหรับการเปลี่ยน role"""
        details = {
            "event": "role_promotion",
            "old_role": old_role,
            "new_role": new_role,
            "promotion_type": promotion_type,  # "manual", "after_verification"
            "timestamp": datetime.now().isoformat()
        }
        
        if ip_address:
            details["ip_address"] = ip_address
        
        if user_agent:
            details["user_agent"] = user_agent

        audit_data = AuditLogCreate(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=AuditAction.PROMOTE_ROLE,
            details=details
        )

        return await self.create_audit_log(audit_data)
