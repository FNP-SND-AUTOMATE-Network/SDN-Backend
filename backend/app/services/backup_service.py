from typing import Optional, List, Dict, Any
from app.models.backup import (
    BackupCreate,
    BackupUpdate,
    BackupResponse,
    RelatedDeviceBackup
)

class BackupService:
    #Service สำหรับจัดการ Backup

    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def create_backup(self, backup_data: BackupCreate, user_id: str) -> Optional[BackupResponse]:
        #สร้าง Backup ใหม่
        try:
            # ตรวจสอบว่า backup_name ซ้ำหรือไม่
            existing_backup = await self.prisma.backup.find_unique(
                where={"backup_name": backup_data.backup_name}
            )
            if existing_backup:
                raise ValueError(f"ชื่อ Backup '{backup_data.backup_name}' มีอยู่ในระบบแล้ว")

            # สร้าง Backup
            backup = await self.prisma.backup.create(
                data={
                    "backup_name": backup_data.backup_name,
                    "description": backup_data.description,
                    "status": backup_data.status.value,
                    "auto_backup": backup_data.auto_backup,
                    "schedule_type": backup_data.schedule_type.value,
                    "cron_expression": backup_data.cron_expression,
                    "retention_days": backup_data.retention_days,
                    "createdByUser": {
                        "connect": {
                            "id": user_id
                        }
                    }
                },
                include={
                    "deviceNetworks": True
                }
            )

            devices_list = []
            if hasattr(backup, 'deviceNetworks') and backup.deviceNetworks:
                for d in backup.deviceNetworks:
                    devices_list.append(RelatedDeviceBackup(id=d.id, device_name=d.device_name))

            from app.core.scheduler import scheduler_manager
            if backup.auto_backup and str(backup.schedule_type) != 'NONE' and backup.cron_expression:
                try:
                    scheduler_manager.add_or_update_backup_job(backup.id, backup.cron_expression)
                except Exception as e:
                    print(f"Scheduler error for new backup {backup.id}: {e}")

            return BackupResponse(
                id=backup.id,
                backup_name=backup.backup_name,
                description=backup.description,
                status=backup.status,
                auto_backup=backup.auto_backup,
                schedule_type=backup.schedule_type,
                cron_expression=backup.cron_expression,
                retention_days=backup.retention_days,
                created_at=backup.createdAt,
                updated_at=backup.updatedAt,
                devices=devices_list,
                device_count=0
            )

        except Exception as e:
            print(f"Error creating backup: {e}")
            if "มีอยู่ในระบบแล้ว" in str(e) or "ไม่พบ" in str(e):
                raise ValueError(str(e))
            raise e

    async def get_backups(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        search: Optional[str] = None,
        auto_backup: Optional[bool] = None,
        include_usage: bool = False
    ) -> tuple[List[BackupResponse], int]:
        #ดึงรายการ Backup ทั้งหมด
        try:
            where_conditions: Dict[str, Any] = {}
            
            if status:
                where_conditions["status"] = status
            
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
                "deviceNetworks": True
            }

            backups = await self.prisma.backup.find_many(
                where=where_conditions,
                skip=skip,
                take=page_size,
                order={"createdAt": "desc"},
                include=include_options
            )

            backup_responses = []
            for backup in backups:
                devices_list = []
                if hasattr(backup, 'deviceNetworks') and backup.deviceNetworks:
                    for d in backup.deviceNetworks:
                        devices_list.append(RelatedDeviceBackup(id=d.id, device_name=d.device_name))

                device_count = len(backup.deviceNetworks) if hasattr(backup, 'deviceNetworks') and backup.deviceNetworks else 0
                
                backup_responses.append(BackupResponse(
                    id=backup.id,
                    backup_name=backup.backup_name,
                    description=backup.description,
                    status=backup.status,
                    auto_backup=backup.auto_backup,
                    schedule_type=backup.schedule_type,
                    cron_expression=backup.cron_expression,
                    retention_days=backup.retention_days,
                    created_by=backup.createdBy,
                    created_at=backup.createdAt,
                    updated_at=backup.updatedAt,
                    devices=devices_list,
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
                "deviceNetworks": True
            }

            backup = await self.prisma.backup.find_unique(
                where={"id": backup_id},
                include=include_options
            )

            if not backup:
                return None

            devices_list = []
            if hasattr(backup, 'deviceNetworks') and backup.deviceNetworks:
                for d in backup.deviceNetworks:
                    devices_list.append(RelatedDeviceBackup(id=d.id, device_name=d.device_name))

            device_count = len(backup.deviceNetworks) if hasattr(backup, 'deviceNetworks') and backup.deviceNetworks else 0

            return BackupResponse(
                id=backup.id,
                backup_name=backup.backup_name,
                description=backup.description,
                status=backup.status,
                auto_backup=backup.auto_backup,
                schedule_type=backup.schedule_type,
                cron_expression=backup.cron_expression,
                retention_days=backup.retention_days,
                created_at=backup.createdAt,
                updated_at=backup.updatedAt,
                devices=devices_list,
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
            
            if update_data.status is not None:
                update_dict["status"] = update_data.status.value
            
            if update_data.auto_backup is not None:
                update_dict["auto_backup"] = update_data.auto_backup

            if update_data.schedule_type is not None:
                update_dict["schedule_type"] = update_data.schedule_type.value

            if update_data.cron_expression is not None:
                update_dict["cron_expression"] = update_data.cron_expression

            if update_data.retention_days is not None:
                update_dict["retention_days"] = update_data.retention_days

            if not update_dict:
                raise ValueError("No data to update")

            updated_backup = await self.prisma.backup.update(
                where={"id": backup_id},
                data=update_dict,
                include={
                    "deviceNetworks": True
                }
            )

            devices_list = []
            if hasattr(updated_backup, 'deviceNetworks') and updated_backup.deviceNetworks:
                for d in updated_backup.deviceNetworks:
                    devices_list.append(RelatedDeviceBackup(id=d.id, device_name=d.device_name))

            device_count = len(updated_backup.deviceNetworks) if updated_backup.deviceNetworks else 0

            device_count = len(updated_backup.deviceNetworks) if updated_backup.deviceNetworks else 0
            
            from app.core.scheduler import scheduler_manager
            
            # If status becomes PAUSED or not auto_backup, remove it
            if updated_backup.status == "PAUSED" or not updated_backup.auto_backup or str(updated_backup.schedule_type) == 'NONE' or not updated_backup.cron_expression:
                scheduler_manager.remove_backup_job(updated_backup.id)
            elif updated_backup.auto_backup and str(updated_backup.schedule_type) != 'NONE' and updated_backup.cron_expression:
                try:
                    scheduler_manager.add_or_update_backup_job(updated_backup.id, updated_backup.cron_expression)
                except Exception as e:
                    print(f"Scheduler error for updated backup {updated_backup.id}: {e}")

            return BackupResponse(
                id=updated_backup.id,
                backup_name=updated_backup.backup_name,
                description=updated_backup.description,
                status=updated_backup.status,
                auto_backup=updated_backup.auto_backup,
                schedule_type=updated_backup.schedule_type,
                cron_expression=updated_backup.cron_expression,
                retention_days=updated_backup.retention_days,
                created_by=updated_backup.createdBy,
                created_at=updated_backup.createdAt,
                updated_at=updated_backup.updatedAt,
                devices=devices_list,
                device_count=device_count
            )

        except Exception as e:
            print(f"Error updating backup: {e}")
            if "ไม่พบ" in str(e) or "มีอยู่ในระบบแล้ว" in str(e) or "No data to update" in str(e):
                raise ValueError(str(e))
            raise e

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
            
            from app.core.scheduler import scheduler_manager
            scheduler_manager.remove_backup_job(backup_id)
            
            return True

        except Exception as e:
            print(f"Error deleting backup: {e}")
            if "ไม่พบ Backup" in str(e) or "ไม่สามารถลบ Backup นี้ได้" in str(e):
                raise ValueError(str(e))
            raise e

    async def pause_backup(self, backup_id: str) -> Optional[BackupResponse]:
        # พักการทำงานชั่วคราว
        update_data = BackupUpdate(status="PAUSED")
        return await self.update_backup(backup_id, update_data)

    async def reactivate_backup(self, backup_id: str) -> Optional[BackupResponse]:
        # กลับมาทำงานต่อ
        update_data = BackupUpdate(status="ONLINE")
        return await self.update_backup(backup_id, update_data)

