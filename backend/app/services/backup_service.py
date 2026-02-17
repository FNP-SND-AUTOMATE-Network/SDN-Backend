from typing import Optional, List, Dict, Any
from app.models.backup import (
    BackupCreate,
    BackupUpdate,
    BackupResponse,
    RelatedPolicyInfoBackup,
    RelatedOSInfoBackup
)

class BackupService:
    #Service สำหรับจัดการ Backup

    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def create_backup(self, backup_data: BackupCreate) -> Optional[BackupResponse]:
        #สร้าง Backup ใหม่
        try:
            # ตรวจสอบว่า backup_name ซ้ำหรือไม่
            existing_backup = await self.prisma.backup.find_unique(
                where={"backup_name": backup_data.backup_name}
            )
            if existing_backup:
                raise ValueError(f"ชื่อ Backup '{backup_data.backup_name}' มีอยู่ในระบบแล้ว")

            # ตรวจสอบ foreign keys
            if backup_data.policy_id:
                policy = await self.prisma.policy.find_unique(where={"id": backup_data.policy_id})
                if not policy:
                    raise ValueError(f"ไม่พบ Policy ID: {backup_data.policy_id}")

            if backup_data.os_id:
                os = await self.prisma.operatingsystem.find_unique(where={"id": backup_data.os_id})
                if not os:
                    raise ValueError(f"ไม่พบ Operating System ID: {backup_data.os_id}")

            # สร้าง Backup
            backup = await self.prisma.backup.create(
                data={
                    "backup_name": backup_data.backup_name,
                    "description": backup_data.description,
                    "policy_id": backup_data.policy_id,
                    "os_id": backup_data.os_id,
                    "status": backup_data.status.value,
                    "auto_backup": backup_data.auto_backup
                },
                include={
                    "policy": True,
                    "operatingSystem": True
                }
            )

            policy_info = None
            if backup.policy:
                policy_info = RelatedPolicyInfoBackup(
                    id=backup.policy.id,
                    policy_name=backup.policy.policy_name
                )

            os_info = None
            if backup.operatingSystem:
                os_info = RelatedOSInfoBackup(
                    id=backup.operatingSystem.id,
                    os_type=backup.operatingSystem.os_type
                )

            return BackupResponse(
                id=backup.id,
                backup_name=backup.backup_name,
                description=backup.description,
                policy_id=backup.policy_id,
                os_id=backup.os_id,
                status=backup.status,
                auto_backup=backup.auto_backup,
                created_at=backup.createdAt,
                updated_at=backup.updatedAt,
                policy=policy_info,
                operating_system=os_info,
                device_count=0
            )

        except Exception as e:
            print(f"Error creating backup: {e}")
            if "มีอยู่ในระบบแล้ว" in str(e) or "ไม่พบ" in str(e):
                raise e
            return None

    async def get_backups(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        search: Optional[str] = None,
        policy_id: Optional[str] = None,
        os_id: Optional[str] = None,
        auto_backup: Optional[bool] = None,
        include_usage: bool = False
    ) -> tuple[List[BackupResponse], int]:
        #ดึงรายการ Backup ทั้งหมด
        try:
            where_conditions: Dict[str, Any] = {}
            
            if status:
                where_conditions["status"] = status
            
            if policy_id:
                where_conditions["policy_id"] = policy_id
            
            if os_id:
                where_conditions["os_id"] = os_id
            
            if auto_backup is not None:
                where_conditions["auto_backup"] = auto_backup
            
            if search:
                where_conditions["OR"] = [
                    {"backup_name": {"contains": search, "mode": "insensitive"}},
                    {"description": {"contains": search, "mode": "insensitive"}}
                ]

            total = await self.prisma.backup.count(where=where_conditions)
            skip = (page - 1) * page_size
            
            include_options: Dict[str, Any] = {
                "policy": True,
                "operatingSystem": True
            }
            if include_usage:
                include_options["deviceNetworks"] = True

            backups = await self.prisma.backup.find_many(
                where=where_conditions,
                skip=skip,
                take=page_size,
                order={"createdAt": "desc"},
                include=include_options
            )

            backup_responses = []
            for backup in backups:
                policy_info = None
                if backup.policy:
                    policy_info = RelatedPolicyInfoBackup(
                        id=backup.policy.id,
                        policy_name=backup.policy.policy_name
                    )

                os_info = None
                if backup.operatingSystem:
                    os_info = RelatedOSInfoBackup(
                        id=backup.operatingSystem.id,
                        os_type=backup.operatingSystem.os_type
                    )

                device_count = len(backup.deviceNetworks) if hasattr(backup, 'deviceNetworks') and backup.deviceNetworks else 0
                
                backup_responses.append(BackupResponse(
                    id=backup.id,
                    backup_name=backup.backup_name,
                    description=backup.description,
                    policy_id=backup.policy_id,
                    os_id=backup.os_id,
                    status=backup.status,
                    auto_backup=backup.auto_backup,
                    created_at=backup.createdAt,
                    updated_at=backup.updatedAt,
                    policy=policy_info,
                    operating_system=os_info,
                    device_count=device_count
                ))

            return backup_responses, total

        except Exception as e:
            print(f"Error getting backups: {e}")
            return [], 0

    async def get_backup_by_id(self, backup_id: str, include_usage: bool = False) -> Optional[BackupResponse]:
        #ดึงข้อมูล Backup ตาม ID
        try:
            include_options: Dict[str, Any] = {
                "policy": True,
                "operatingSystem": True
            }
            if include_usage:
                include_options["deviceNetworks"] = True

            backup = await self.prisma.backup.find_unique(
                where={"id": backup_id},
                include=include_options
            )

            if not backup:
                return None

            policy_info = None
            if backup.policy:
                policy_info = RelatedPolicyInfoBackup(
                    id=backup.policy.id,
                    policy_name=backup.policy.policy_name
                )

            os_info = None
            if backup.operatingSystem:
                os_info = RelatedOSInfoBackup(
                    id=backup.operatingSystem.id,
                    os_type=backup.operatingSystem.os_type
                )

            device_count = len(backup.deviceNetworks) if hasattr(backup, 'deviceNetworks') and backup.deviceNetworks else 0

            return BackupResponse(
                id=backup.id,
                backup_name=backup.backup_name,
                description=backup.description,
                policy_id=backup.policy_id,
                os_id=backup.os_id,
                status=backup.status,
                auto_backup=backup.auto_backup,
                created_at=backup.createdAt,
                updated_at=backup.updatedAt,
                policy=policy_info,
                operating_system=os_info,
                device_count=device_count
            )

        except Exception as e:
            print(f"Error getting backup by id: {e}")
            return None

    async def update_backup(self, backup_id: str, update_data: BackupUpdate) -> Optional[BackupResponse]:
        #อัปเดต Backup
        try:
            existing_backup = await self.prisma.backup.find_unique(where={"id": backup_id})

            if not existing_backup:
                raise ValueError("ไม่พบ Backup ที่ต้องการอัปเดต")

            update_dict: Dict[str, Any] = {}
            
            if update_data.backup_name is not None:
                if update_data.backup_name != existing_backup.backup_name:
                    duplicate = await self.prisma.backup.find_unique(
                        where={"backup_name": update_data.backup_name}
                    )
                    if duplicate:
                        raise ValueError(f"ชื่อ Backup '{update_data.backup_name}' มีอยู่ในระบบแล้ว")
                update_dict["backup_name"] = update_data.backup_name

            if update_data.description is not None:
                update_dict["description"] = update_data.description
            
            if update_data.policy_id is not None:
                if update_data.policy_id:
                    policy = await self.prisma.policy.find_unique(where={"id": update_data.policy_id})
                    if not policy:
                        raise ValueError(f"ไม่พบ Policy ID: {update_data.policy_id}")
                update_dict["policy_id"] = update_data.policy_id
            
            if update_data.os_id is not None:
                if update_data.os_id:
                    os = await self.prisma.operatingsystem.find_unique(where={"id": update_data.os_id})
                    if not os:
                        raise ValueError(f"ไม่พบ Operating System ID: {update_data.os_id}")
                update_dict["os_id"] = update_data.os_id
            
            if update_data.status is not None:
                update_dict["status"] = update_data.status.value
            
            if update_data.auto_backup is not None:
                update_dict["auto_backup"] = update_data.auto_backup

            if not update_dict:
                raise ValueError("ไม่มีข้อมูลที่จะอัปเดต")

            updated_backup = await self.prisma.backup.update(
                where={"id": backup_id},
                data=update_dict,
                include={
                    "policy": True,
                    "operatingSystem": True,
                    "deviceNetworks": True
                }
            )

            policy_info = None
            if updated_backup.policy:
                policy_info = RelatedPolicyInfoBackup(
                    id=updated_backup.policy.id,
                    policy_name=updated_backup.policy.policy_name
                )

            os_info = None
            if updated_backup.operatingSystem:
                os_info = RelatedOSInfoBackup(
                    id=updated_backup.operatingSystem.id,
                    os_type=updated_backup.operatingSystem.os_type
                )

            device_count = len(updated_backup.deviceNetworks) if updated_backup.deviceNetworks else 0

            return BackupResponse(
                id=updated_backup.id,
                backup_name=updated_backup.backup_name,
                description=updated_backup.description,
                policy_id=updated_backup.policy_id,
                os_id=updated_backup.os_id,
                status=updated_backup.status,
                auto_backup=updated_backup.auto_backup,
                created_at=updated_backup.createdAt,
                updated_at=updated_backup.updatedAt,
                policy=policy_info,
                operating_system=os_info,
                device_count=device_count
            )

        except Exception as e:
            print(f"Error updating backup: {e}")
            if "ไม่พบ" in str(e) or "มีอยู่ในระบบแล้ว" in str(e) or "ไม่มีข้อมูลที่จะอัปเดต" in str(e):
                raise e
            return None

    async def delete_backup(self, backup_id: str, force: bool = False) -> bool:
        #ลบ Backup
        try:
            existing_backup = await self.prisma.backup.find_unique(
                where={"id": backup_id},
                include={"deviceNetworks": True}
            )

            if not existing_backup:
                raise ValueError("ไม่พบ Backup ที่ต้องการลบ")

            device_count = len(existing_backup.deviceNetworks) if existing_backup.deviceNetworks else 0

            if not force and device_count > 0:
                raise ValueError(
                    f"ไม่สามารถลบ Backup นี้ได้ เนื่องจากกำลังถูกใช้งานโดย {device_count} Device"
                )

            await self.prisma.backup.delete(where={"id": backup_id})
            return True

        except Exception as e:
            print(f"Error deleting backup: {e}")
            if "ไม่พบ Backup" in str(e) or "ไม่สามารถลบ Backup นี้ได้" in str(e):
                raise e
            return False

