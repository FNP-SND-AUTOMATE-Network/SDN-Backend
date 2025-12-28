from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.operating_system import (
    OperatingSystemCreate,
    OperatingSystemUpdate,
    OperatingSystemResponse,
    OperatingSystemUsageResponse,
    TagInfo
)

class OperatingSystemService:
    #Service สำหรับจัดการ Operating System

    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def create_operating_system(self, os_data: OperatingSystemCreate) -> Optional[OperatingSystemResponse]:
        #สร้าง Operating System ใหม่
        try:
            #ตรวจสอบว่า os_name ซ้ำหรือไม่
            existing_os = await self.prisma.operatingsystem.find_unique(
                where={"os_name": os_data.os_name}
            )
            if existing_os:
                raise ValueError(f"ชื่อ OS '{os_data.os_name}' มีอยู่ในระบบแล้ว")


            #สร้าง Operating System ใหม่
            os = await self.prisma.operatingsystem.create(
                data={
                    "os_name": os_data.os_name,
                    "os_type": os_data.os_type.value,
                    "description": os_data.description
                },
                include={
                    "tags": True
                }
            )

            #แปลง tags info (many-to-many)
            tags_info = []
            if hasattr(os, 'tags') and os.tags:
                for tag in os.tags:
                    tags_info.append(TagInfo(
                        tag_id=tag.tag_id,
                        tag_name=tag.tag_name,
                        color=tag.color,
                        type=tag.type
                    ))

            return OperatingSystemResponse(
                id=os.id,
                os_name=os.os_name,
                os_type=os.os_type,
                description=os.description,
                created_at=os.createdAt,
                updated_at=os.updatedAt,
                tags=tags_info,
                device_count=0,
                backup_count=0,
                total_usage=0
            )

        except Exception as e:
            print(f"Error creating operating system: {e}")
            if "มีอยู่ในระบบแล้ว" in str(e) or "ไม่พบ Tag" in str(e):
                raise e
            return None

    async def get_operating_systems(
        self,
        page: int = 1,
        page_size: int = 20,
        os_type: Optional[str] = None,
        search: Optional[str] = None,
        include_usage: bool = False
    ) -> tuple[List[OperatingSystemResponse], int]:
        #ดึงรายการ Operating System ทั้งหมด พร้อม pagination และ filter
        try:
            #สร้าง filter conditions
            where_conditions: Dict[str, Any] = {}
            
            if os_type:
                where_conditions["os_type"] = os_type
            
            if search:
                where_conditions["OR"] = [
                    {"os_name": {"contains": search, "mode": "insensitive"}},
                    {"description": {"contains": search, "mode": "insensitive"}}
                ]

            #นับจำนวนทั้งหมด
            total = await self.prisma.operatingsystem.count(where=where_conditions)

            #ดึงข้อมูลตาม pagination
            skip = (page - 1) * page_size
            
            # Include relations ถ้าต้องการนับการใช้งาน
            include_options: Dict[str, Any] = {"tags": True}
            if include_usage:
                include_options["deviceNetworks"] = True
                include_options["backups"] = True

            operating_systems = await self.prisma.operatingsystem.find_many(
                where=where_conditions,
                skip=skip,
                take=page_size,
                order={"createdAt": "desc"},
                include=include_options
            )

            #แปลงเป็น response model
            os_responses = []
            for os in operating_systems:
                #แปลง tags info (many-to-many)
                tags_info = []
                if hasattr(os, 'tags') and os.tags:
                    for tag in os.tags:
                        tags_info.append(TagInfo(
                            tag_id=tag.tag_id,
                            tag_name=tag.tag_name,
                            color=tag.color,
                            type=tag.type
                        ))

                device_count = len(os.deviceNetworks) if hasattr(os, 'deviceNetworks') and os.deviceNetworks else 0
                backup_count = len(os.backups) if hasattr(os, 'backups') and os.backups else 0
                
                os_responses.append(OperatingSystemResponse(
                    id=os.id,
                    os_name=os.os_name,
                    os_type=os.os_type,
                    description=os.description,
                    created_at=os.createdAt,
                    updated_at=os.updatedAt,
                    tags=tags_info,
                    device_count=device_count,
                    backup_count=backup_count,
                    total_usage=device_count + backup_count
                ))

            return os_responses, total

        except Exception as e:
            print(f"Error getting operating systems: {e}")
            return [], 0

    async def get_operating_system_by_id(self, os_id: str, include_usage: bool = False) -> Optional[OperatingSystemResponse]:
        #ดึงข้อมูล Operating System ตาม ID
        try:
            include_options: Dict[str, Any] = {"tags": True}
            if include_usage:
                include_options["deviceNetworks"] = True
                include_options["backups"] = True

            os = await self.prisma.operatingsystem.find_unique(
                where={"id": os_id},
                include=include_options
            )

            if not os:
                return None

            #แปลง tags info (many-to-many)
            tags_info = []
            if hasattr(os, 'tags') and os.tags:
                for tag in os.tags:
                    tags_info.append(TagInfo(
                        tag_id=tag.tag_id,
                        tag_name=tag.tag_name,
                        color=tag.color,
                        type=tag.type
                    ))

            device_count = len(os.deviceNetworks) if hasattr(os, 'deviceNetworks') and os.deviceNetworks else 0
            backup_count = len(os.backups) if hasattr(os, 'backups') and os.backups else 0

            return OperatingSystemResponse(
                id=os.id,
                os_name=os.os_name,
                os_type=os.os_type,
                description=os.description,
                created_at=os.createdAt,
                updated_at=os.updatedAt,
                tags=tags_info,
                device_count=device_count,
                backup_count=backup_count,
                total_usage=device_count + backup_count
            )

        except Exception as e:
            print(f"Error getting operating system by id: {e}")
            return None

    async def get_operating_system_usage(self, os_id: str) -> Optional[OperatingSystemUsageResponse]:
        #ดึงข้อมูลการใช้งาน Operating System โดยละเอียด
        try:
            os = await self.prisma.operatingsystem.find_unique(
                where={"id": os_id},
                include={
                    "deviceNetworks": {
                        "select": {
                            "id": True,
                            "serial_number": True,
                            "device_name": True,
                            "device_model": True,
                            "type": True,
                            "status": True,
                            "ip_address": True
                        }
                    },
                    "backups": {
                        "select": {
                            "id": True,
                            "backup_name": True,
                            "status": True,
                            "auto_backup": True,
                            "description": True
                        }
                    }
                }
            )

            if not os:
                return None

            #แปลง Prisma objects เป็น dict
            device_networks = [dict(d) for d in os.deviceNetworks] if os.deviceNetworks else []
            backups = [dict(b) for b in os.backups] if os.backups else []

            return OperatingSystemUsageResponse(
                id=os.id,
                os_name=os.os_name,
                os_type=os.os_type,
                device_networks=device_networks,
                backups=backups,
                total_usage=len(device_networks) + len(backups)
            )

        except Exception as e:
            print(f"Error getting operating system usage: {e}")
            return None

    async def update_operating_system(
        self,
        os_id: str,
        update_data: OperatingSystemUpdate
    ) -> Optional[OperatingSystemResponse]:
        #อัปเดต Operating System
        try:
            #ตรวจสอบว่า OS มีอยู่หรือไม่
            existing_os = await self.prisma.operatingsystem.find_unique(
                where={"id": os_id}
            )

            if not existing_os:
                raise ValueError("ไม่พบ Operating System ที่ต้องการอัปเดต")

            # เตรียมข้อมูลสำหรับอัปเดต
            update_dict: Dict[str, Any] = {}
            
            if update_data.os_name is not None:
                # ตรวจสอบว่า os_name ซ้ำหรือไม่
                if update_data.os_name != existing_os.os_name:
                    duplicate = await self.prisma.operatingsystem.find_unique(
                        where={"os_name": update_data.os_name}
                    )
                    if duplicate:
                        raise ValueError(f"ชื่อ OS '{update_data.os_name}' มีอยู่ในระบบแล้ว")
                update_dict["os_name"] = update_data.os_name

            if update_data.os_type is not None:
                update_dict["os_type"] = update_data.os_type.value

            if update_data.description is not None:
                update_dict["description"] = update_data.description

            # ตรวจสอบว่ามีข้อมูลที่จะอัปเดตหรือไม่
            if not update_dict:
                raise ValueError("ไม่มีข้อมูลที่จะอัปเดต")

            # อัปเดตข้อมูล
            updated_os = await self.prisma.operatingsystem.update(
                where={"id": os_id},
                data=update_dict,
                include={
                    "tags": True,
                    "deviceNetworks": True,
                    "backups": True
                }
            )

            #แปลง tags info (many-to-many)
            tags_info = []
            if hasattr(updated_os, 'tags') and updated_os.tags:
                for tag in updated_os.tags:
                    tags_info.append(TagInfo(
                        tag_id=tag.tag_id,
                        tag_name=tag.tag_name,
                        color=tag.color,
                        type=tag.type
                    ))

            device_count = len(updated_os.deviceNetworks) if updated_os.deviceNetworks else 0
            backup_count = len(updated_os.backups) if updated_os.backups else 0

            return OperatingSystemResponse(
                id=updated_os.id,
                os_name=updated_os.os_name,
                os_type=updated_os.os_type,
                description=updated_os.description,
                created_at=updated_os.createdAt,
                updated_at=updated_os.updatedAt,
                tags=tags_info,
                device_count=device_count,
                backup_count=backup_count,
                total_usage=device_count + backup_count
            )

        except Exception as e:
            print(f"Error updating operating system: {e}")
            if "ไม่พบ Operating System" in str(e) or "มีอยู่ในระบบแล้ว" in str(e) or "ไม่มีข้อมูลที่จะอัปเดต" in str(e) or "ไม่พบ Tag" in str(e):
                raise e
            return None

    async def delete_operating_system(self, os_id: str, force: bool = False) -> bool:
        #ลบ Operating System
        try:
            #ตรวจสอบว่า OS มีอยู่หรือไม่
            existing_os = await self.prisma.operatingsystem.find_unique(
                where={"id": os_id},
                include={
                    "deviceNetworks": True,
                    "backups": True
                }
            )

            if not existing_os:
                raise ValueError("ไม่พบ Operating System ที่ต้องการลบ")

            # นับการใช้งาน
            device_count = len(existing_os.deviceNetworks) if existing_os.deviceNetworks else 0
            backup_count = len(existing_os.backups) if existing_os.backups else 0
            total_usage = device_count + backup_count

            # ตรวจสอบว่ามีการใช้งานหรือไม่
            if not force and total_usage > 0:
                usage_details = []
                if device_count > 0:
                    usage_details.append(f"{device_count} Device")
                if backup_count > 0:
                    usage_details.append(f"{backup_count} Backup")
                
                raise ValueError(
                    f"ไม่สามารถลบ OS นี้ได้ เนื่องจากกำลังถูกใช้งานโดย: {', '.join(usage_details)}"
                )

            # ลบ OS
            await self.prisma.operatingsystem.delete(
                where={"id": os_id}
            )

            return True

        except Exception as e:
            print(f"Error deleting operating system: {e}")
            if "ไม่พบ Operating System" in str(e) or "ไม่สามารถลบ OS นี้ได้" in str(e):
                raise e
            return False

    async def assign_tags(self, os_id: str, tag_ids: list[str]) -> Optional[OperatingSystemResponse]:
        #เพิ่ม tags ให้กับ Operating System
        try:
            #ตรวจสอบว่า OS มีอยู่จริง
            os = await self.prisma.operatingsystem.find_unique(where={"id": os_id})
            if not os:
                raise ValueError("ไม่พบ Operating System")

            # ตรวจสอบว่า tags มีอยู่จริงทั้งหมด
            for tag_id in tag_ids:
                tag = await self.prisma.tag.find_unique(where={"tag_id": tag_id})
                if not tag:
                    raise ValueError(f"ไม่พบ Tag ID: {tag_id}")

            # เชื่อมโยง tags กับ OS
            updated_os = await self.prisma.operatingsystem.update(
                where={"id": os_id},
                data={
                    "tags": {
                        "connect": [{"tag_id": tag_id} for tag_id in tag_ids]
                    }
                },
                include={
                    "tags": True,
                    "deviceNetworks": True,
                    "backups": True
                }
            )

            #แปลง tags info
            tags_info = []
            if hasattr(updated_os, 'tags') and updated_os.tags:
                for tag in updated_os.tags:
                    tags_info.append(TagInfo(
                        tag_id=tag.tag_id,
                        tag_name=tag.tag_name,
                        color=tag.color,
                        type=tag.type
                    ))

            device_count = len(updated_os.deviceNetworks) if updated_os.deviceNetworks else 0
            backup_count = len(updated_os.backups) if updated_os.backups else 0

            return OperatingSystemResponse(
                id=updated_os.id,
                os_name=updated_os.os_name,
                os_type=updated_os.os_type,
                description=updated_os.description,
                created_at=updated_os.createdAt,
                updated_at=updated_os.updatedAt,
                tags=tags_info,
                device_count=device_count,
                backup_count=backup_count,
                total_usage=device_count + backup_count
            )

        except Exception as e:
            print(f"Error assigning tags to OS: {e}")
            if "ไม่พบ" in str(e):
                raise e
            return None

    async def remove_tags(self, os_id: str, tag_ids: list[str]) -> Optional[OperatingSystemResponse]:
        #ลบ tags ออกจาก Operating System
        try:
            #ตรวจสอบว่า OS มีอยู่จริง
            os = await self.prisma.operatingsystem.find_unique(where={"id": os_id})
            if not os:
                raise ValueError("ไม่พบ Operating System")

            # ตัดการเชื่อมโยง tags
            updated_os = await self.prisma.operatingsystem.update(
                where={"id": os_id},
                data={
                    "tags": {
                        "disconnect": [{"tag_id": tag_id} for tag_id in tag_ids]
                    }
                },
                include={
                    "tags": True,
                    "deviceNetworks": True,
                    "backups": True
                }
            )

            #แปลง tags info
            tags_info = []
            if hasattr(updated_os, 'tags') and updated_os.tags:
                for tag in updated_os.tags:
                    tags_info.append(TagInfo(
                        tag_id=tag.tag_id,
                        tag_name=tag.tag_name,
                        color=tag.color,
                        type=tag.type
                    ))

            device_count = len(updated_os.deviceNetworks) if updated_os.deviceNetworks else 0
            backup_count = len(updated_os.backups) if updated_os.backups else 0

            return OperatingSystemResponse(
                id=updated_os.id,
                os_name=updated_os.os_name,
                os_type=updated_os.os_type,
                description=updated_os.description,
                created_at=updated_os.createdAt,
                updated_at=updated_os.updatedAt,
                tags=tags_info,
                device_count=device_count,
                backup_count=backup_count,
                total_usage=device_count + backup_count
            )

        except Exception as e:
            print(f"Error removing tags from OS: {e}")
            if "ไม่พบ" in str(e):
                raise e
            return None

