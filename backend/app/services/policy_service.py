from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.policy import (
    PolicyCreate,
    PolicyUpdate,
    PolicyResponse,
    RelatedUserInfo,
    ParentPolicyInfo
)

class PolicyService:
    """Service สำหรับจัดการ Policy"""

    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def create_policy(self, policy_data: PolicyCreate, user_id: str) -> Optional[PolicyResponse]:
        """สร้าง Policy ใหม่"""
        try:
            # ตรวจสอบว่า policy_name ซ้ำหรือไม่
            existing_policy = await self.prisma.policy.find_unique(
                where={"policy_name": policy_data.policy_name}
            )
            if existing_policy:
                raise ValueError(f"ชื่อ Policy '{policy_data.policy_name}' มีอยู่ในระบบแล้ว")

            # ถ้ามี parent_policy_id ให้ตรวจสอบว่ามีอยู่จริง
            if policy_data.parent_policy_id:
                parent = await self.prisma.policy.find_unique(
                    where={"id": policy_data.parent_policy_id}
                )
                if not parent:
                    raise ValueError(f"ไม่พบ Parent Policy ID: {policy_data.parent_policy_id}")

            # สร้าง Policy ใหม่
            policy = await self.prisma.policy.create(
                data={
                    "policy_name": policy_data.policy_name,
                    "description": policy_data.description,
                    "parent_policy_id": policy_data.parent_policy_id,
                    "createdBy": user_id
                },
                include={
                    "createdByUser": True,
                    "parent_policy": True
                }
            )

            # แปลง created_by_user info
            created_by_user = None
            if policy.createdByUser:
                created_by_user = RelatedUserInfo(
                    id=policy.createdByUser.id,
                    email=policy.createdByUser.email,
                    name=policy.createdByUser.name,
                    surname=policy.createdByUser.surname
                )

            # แปลง parent_policy info
            parent_policy = None
            if policy.parent_policy:
                parent_policy = ParentPolicyInfo(
                    id=policy.parent_policy.id,
                    policy_name=policy.parent_policy.policy_name
                )

            return PolicyResponse(
                id=policy.id,
                policy_name=policy.policy_name,
                description=policy.description,
                parent_policy_id=policy.parent_policy_id,
                created_by=policy.createdBy,
                created_at=policy.createdAt,
                updated_at=policy.updatedAt,
                created_by_user=created_by_user,
                parent_policy=parent_policy,
                device_count=0,
                backup_count=0,
                child_count=0,
                total_usage=0
            )

        except Exception as e:
            print(f"Error creating policy: {e}")
            if "มีอยู่ในระบบแล้ว" in str(e) or "ไม่พบ Parent Policy" in str(e):
                raise e
            return None

    async def get_policies(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        parent_policy_id: Optional[str] = None,
        include_usage: bool = False
    ) -> tuple[List[PolicyResponse], int]:
        """ดึงรายการ Policy ทั้งหมด"""
        try:
            where_conditions: Dict[str, Any] = {}
            
            if parent_policy_id:
                where_conditions["parent_policy_id"] = parent_policy_id
            
            if search:
                where_conditions["OR"] = [
                    {"policy_name": {"contains": search, "mode": "insensitive"}},
                    {"description": {"contains": search, "mode": "insensitive"}}
                ]

            total = await self.prisma.policy.count(where=where_conditions)

            skip = (page - 1) * page_size
            
            include_options: Dict[str, Any] = {
                "createdByUser": True,
                "parent_policy": True
            }
            if include_usage:
                include_options["deviceNetworks"] = True
                include_options["backups"] = True
                include_options["child_policies"] = True

            policies = await self.prisma.policy.find_many(
                where=where_conditions,
                skip=skip,
                take=page_size,
                order={"createdAt": "desc"},
                include=include_options
            )

            policy_responses = []
            for policy in policies:
                created_by_user = None
                if policy.createdByUser:
                    created_by_user = RelatedUserInfo(
                        id=policy.createdByUser.id,
                        email=policy.createdByUser.email,
                        name=policy.createdByUser.name,
                        surname=policy.createdByUser.surname
                    )

                parent_policy = None
                if policy.parent_policy:
                    parent_policy = ParentPolicyInfo(
                        id=policy.parent_policy.id,
                        policy_name=policy.parent_policy.policy_name
                    )

                device_count = len(policy.deviceNetworks) if hasattr(policy, 'deviceNetworks') and policy.deviceNetworks else 0
                backup_count = len(policy.backups) if hasattr(policy, 'backups') and policy.backups else 0
                child_count = len(policy.child_policies) if hasattr(policy, 'child_policies') and policy.child_policies else 0
                
                policy_responses.append(PolicyResponse(
                    id=policy.id,
                    policy_name=policy.policy_name,
                    description=policy.description,
                    parent_policy_id=policy.parent_policy_id,
                    created_by=policy.createdBy,
                    created_at=policy.createdAt,
                    updated_at=policy.updatedAt,
                    created_by_user=created_by_user,
                    parent_policy=parent_policy,
                    device_count=device_count,
                    backup_count=backup_count,
                    child_count=child_count,
                    total_usage=device_count + backup_count + child_count
                ))

            return policy_responses, total

        except Exception as e:
            print(f"Error getting policies: {e}")
            return [], 0

    async def get_policy_by_id(self, policy_id: str, include_usage: bool = False) -> Optional[PolicyResponse]:
        """ดึงข้อมูล Policy ตาม ID"""
        try:
            include_options: Dict[str, Any] = {
                "createdByUser": True,
                "parent_policy": True
            }
            if include_usage:
                include_options["deviceNetworks"] = True
                include_options["backups"] = True
                include_options["child_policies"] = True

            policy = await self.prisma.policy.find_unique(
                where={"id": policy_id},
                include=include_options
            )

            if not policy:
                return None

            created_by_user = None
            if policy.createdByUser:
                created_by_user = RelatedUserInfo(
                    id=policy.createdByUser.id,
                    email=policy.createdByUser.email,
                    name=policy.createdByUser.name,
                    surname=policy.createdByUser.surname
                )

            parent_policy = None
            if policy.parent_policy:
                parent_policy = ParentPolicyInfo(
                    id=policy.parent_policy.id,
                    policy_name=policy.parent_policy.policy_name
                )

            device_count = len(policy.deviceNetworks) if hasattr(policy, 'deviceNetworks') and policy.deviceNetworks else 0
            backup_count = len(policy.backups) if hasattr(policy, 'backups') and policy.backups else 0
            child_count = len(policy.child_policies) if hasattr(policy, 'child_policies') and policy.child_policies else 0

            return PolicyResponse(
                id=policy.id,
                policy_name=policy.policy_name,
                description=policy.description,
                parent_policy_id=policy.parent_policy_id,
                created_by=policy.createdBy,
                created_at=policy.createdAt,
                updated_at=policy.updatedAt,
                created_by_user=created_by_user,
                parent_policy=parent_policy,
                device_count=device_count,
                backup_count=backup_count,
                child_count=child_count,
                total_usage=device_count + backup_count + child_count
            )

        except Exception as e:
            print(f"Error getting policy by id: {e}")
            return None

    async def update_policy(self, policy_id: str, update_data: PolicyUpdate) -> Optional[PolicyResponse]:
        """อัปเดต Policy"""
        try:
            existing_policy = await self.prisma.policy.find_unique(
                where={"id": policy_id}
            )

            if not existing_policy:
                raise ValueError("ไม่พบ Policy ที่ต้องการอัปเดต")

            update_dict: Dict[str, Any] = {}
            
            if update_data.policy_name is not None:
                if update_data.policy_name != existing_policy.policy_name:
                    duplicate = await self.prisma.policy.find_unique(
                        where={"policy_name": update_data.policy_name}
                    )
                    if duplicate:
                        raise ValueError(f"ชื่อ Policy '{update_data.policy_name}' มีอยู่ในระบบแล้ว")
                update_dict["policy_name"] = update_data.policy_name

            if update_data.description is not None:
                update_dict["description"] = update_data.description
            
            if update_data.parent_policy_id is not None:
                if update_data.parent_policy_id:
                    # ตรวจสอบว่า parent policy มีอยู่จริง
                    parent = await self.prisma.policy.find_unique(
                        where={"id": update_data.parent_policy_id}
                    )
                    if not parent:
                        raise ValueError(f"ไม่พบ Parent Policy ID: {update_data.parent_policy_id}")
                    
                    # ป้องกัน circular reference
                    if update_data.parent_policy_id == policy_id:
                        raise ValueError("ไม่สามารถกำหนด Policy เป็น parent ของตัวเองได้")
                
                update_dict["parent_policy_id"] = update_data.parent_policy_id

            if not update_dict:
                raise ValueError("ไม่มีข้อมูลที่จะอัปเดต")

            updated_policy = await self.prisma.policy.update(
                where={"id": policy_id},
                data=update_dict,
                include={
                    "createdByUser": True,
                    "parent_policy": True,
                    "deviceNetworks": True,
                    "backups": True,
                    "child_policies": True
                }
            )

            created_by_user = None
            if updated_policy.createdByUser:
                created_by_user = RelatedUserInfo(
                    id=updated_policy.createdByUser.id,
                    email=updated_policy.createdByUser.email,
                    name=updated_policy.createdByUser.name,
                    surname=updated_policy.createdByUser.surname
                )

            parent_policy = None
            if updated_policy.parent_policy:
                parent_policy = ParentPolicyInfo(
                    id=updated_policy.parent_policy.id,
                    policy_name=updated_policy.parent_policy.policy_name
                )

            device_count = len(updated_policy.deviceNetworks) if updated_policy.deviceNetworks else 0
            backup_count = len(updated_policy.backups) if updated_policy.backups else 0
            child_count = len(updated_policy.child_policies) if updated_policy.child_policies else 0

            return PolicyResponse(
                id=updated_policy.id,
                policy_name=updated_policy.policy_name,
                description=updated_policy.description,
                parent_policy_id=updated_policy.parent_policy_id,
                created_by=updated_policy.createdBy,
                created_at=updated_policy.createdAt,
                updated_at=updated_policy.updatedAt,
                created_by_user=created_by_user,
                parent_policy=parent_policy,
                device_count=device_count,
                backup_count=backup_count,
                child_count=child_count,
                total_usage=device_count + backup_count + child_count
            )

        except Exception as e:
            print(f"Error updating policy: {e}")
            if "ไม่พบ Policy" in str(e) or "มีอยู่ในระบบแล้ว" in str(e) or "ไม่มีข้อมูลที่จะอัปเดต" in str(e) or "ไม่สามารถกำหนด" in str(e):
                raise e
            return None

    async def delete_policy(self, policy_id: str, force: bool = False) -> bool:
        """ลบ Policy"""
        try:
            existing_policy = await self.prisma.policy.find_unique(
                where={"id": policy_id},
                include={
                    "deviceNetworks": True,
                    "backups": True,
                    "child_policies": True
                }
            )

            if not existing_policy:
                raise ValueError("ไม่พบ Policy ที่ต้องการลบ")

            device_count = len(existing_policy.deviceNetworks) if existing_policy.deviceNetworks else 0
            backup_count = len(existing_policy.backups) if existing_policy.backups else 0
            child_count = len(existing_policy.child_policies) if existing_policy.child_policies else 0
            total_usage = device_count + backup_count + child_count

            if not force and total_usage > 0:
                usage_details = []
                if device_count > 0:
                    usage_details.append(f"{device_count} Device")
                if backup_count > 0:
                    usage_details.append(f"{backup_count} Backup")
                if child_count > 0:
                    usage_details.append(f"{child_count} Child Policy")
                
                raise ValueError(
                    f"ไม่สามารถลบ Policy นี้ได้ เนื่องจากกำลังถูกใช้งานโดย: {', '.join(usage_details)}"
                )

            await self.prisma.policy.delete(
                where={"id": policy_id}
            )

            return True

        except Exception as e:
            print(f"Error deleting policy: {e}")
            if "ไม่พบ Policy" in str(e) or "ไม่สามารถลบ Policy นี้ได้" in str(e):
                raise e
            return False

