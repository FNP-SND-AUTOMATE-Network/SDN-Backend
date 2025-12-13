from typing import Optional, List, Dict, Any
from datetime import datetime
import random
from app.models.tag import (
    TagCreate,
    TagUpdate,
    TagResponse,
    TagUsageResponse
)

class TagService:
    """Service สำหรับจัดการ Tag"""
    
    # ชุดสีสวยๆ สำหรับใช้กับ Tag (Material Design & Tailwind CSS inspired)
    DEFAULT_COLORS = [
        "#3B82F6",  # Blue
        "#10B981",  # Green
        "#F59E0B",  # Amber
        "#EF4444",  # Red
        "#8B5CF6",  # Purple
        "#EC4899",  # Pink
        "#06B6D4",  # Cyan
        "#84CC16",  # Lime
        "#F97316",  # Orange
        "#6366F1",  # Indigo
        "#14B8A6",  # Teal
        "#A855F7",  # Violet
        "#F43F5E",  # Rose
        "#22C55E",  # Emerald
        "#EAB308",  # Yellow
        "#6B7280",  # Gray
    ]
    
    @staticmethod
    def _generate_random_color() -> str:
        """สุ่มสีจากชุดสีที่กำหนดไว้"""
        return random.choice(TagService.DEFAULT_COLORS)

    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def create_tag(self, tag_data: TagCreate) -> Optional[TagResponse]:
        """สร้าง Tag ใหม่"""
        try:
            # ตรวจสอบว่า tag_name ซ้ำหรือไม่
            existing_tag = await self.prisma.tag.find_unique(
                where={"tag_name": tag_data.tag_name}
            )
            if existing_tag:
                raise ValueError(f"ชื่อ Tag '{tag_data.tag_name}' มีอยู่ในระบบแล้ว")

            # ใช้สีที่ระบุมา หรือสุ่มสีถ้าไม่ได้ระบุ
            color = tag_data.color if tag_data.color != "#3B82F6" else self._generate_random_color()

            # สร้าง Tag ใหม่
            tag = await self.prisma.tag.create(
                data={
                    "tag_name": tag_data.tag_name,
                    "description": tag_data.description,
                    "type": tag_data.type.value,
                    "color": color
                }
            )

            return TagResponse(
                tag_id=tag.tag_id,
                tag_name=tag.tag_name,
                description=tag.description,
                type=tag.type,
                color=tag.color,
                created_at=tag.createdAt,
                updated_at=tag.updatedAt,
                device_count=0,
                os_count=0,
                template_count=0,
                total_usage=0
            )

        except Exception as e:
            print(f"Error creating tag: {e}")
            if "มีอยู่ในระบบแล้ว" in str(e):
                raise e
            return None

    async def get_tags(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        include_usage: bool = False
    ) -> tuple[List[TagResponse], int]:
        """ดึงรายการ Tag ทั้งหมด พร้อม pagination และ filter"""
        try:
            # สร้าง filter conditions
            where_conditions: Dict[str, Any] = {}
            
            if search:
                where_conditions["OR"] = [
                    {"tag_name": {"contains": search, "mode": "insensitive"}},
                    {"description": {"contains": search, "mode": "insensitive"}}
                ]

            # นับจำนวนทั้งหมด
            total = await self.prisma.tag.count(where=where_conditions)

            # ดึงข้อมูลตาม pagination
            skip = (page - 1) * page_size
            
            # Include relations ถ้าต้องการนับการใช้งาน
            include_options = {}
            if include_usage:
                include_options = {
                    "deviceNetworks": True,
                    "operatingSystems": True,
                    "configurationTemplates": True
                }

            tags = await self.prisma.tag.find_many(
                where=where_conditions,
                skip=skip,
                take=page_size,
                order={"createdAt": "desc"},
                include=include_options
            )

            # แปลงเป็น response model
            tag_responses = []
            for tag in tags:
                device_count = len(tag.deviceNetworks) if hasattr(tag, 'deviceNetworks') and tag.deviceNetworks else 0
                os_count = len(tag.operatingSystems) if hasattr(tag, 'operatingSystems') and tag.operatingSystems else 0
                template_count = len(tag.configurationTemplates) if hasattr(tag, 'configurationTemplates') and tag.configurationTemplates else 0
                
                tag_responses.append(TagResponse(
                    tag_id=tag.tag_id,
                    tag_name=tag.tag_name,
                    description=tag.description,
                    type=tag.type,
                    color=tag.color,
                    created_at=tag.createdAt,
                    updated_at=tag.updatedAt,
                    device_count=device_count,
                    os_count=os_count,
                    template_count=template_count,
                    total_usage=device_count + os_count + template_count
                ))

            return tag_responses, total

        except Exception as e:
            print(f"Error getting tags: {e}")
            return [], 0

    async def get_tag_by_id(self, tag_id: str, include_usage: bool = False) -> Optional[TagResponse]:
        """ดึงข้อมูล Tag ตาม ID"""
        try:
            include_options = {}
            if include_usage:
                include_options = {
                    "deviceNetworks": True,
                    "operatingSystems": True,
                    "configurationTemplates": True
                }

            tag = await self.prisma.tag.find_unique(
                where={"tag_id": tag_id},
                include=include_options
            )

            if not tag:
                return None

            device_count = len(tag.deviceNetworks) if hasattr(tag, 'deviceNetworks') and tag.deviceNetworks else 0
            os_count = len(tag.operatingSystems) if hasattr(tag, 'operatingSystems') and tag.operatingSystems else 0
            template_count = len(tag.configurationTemplates) if hasattr(tag, 'configurationTemplates') and tag.configurationTemplates else 0

            return TagResponse(
                tag_id=tag.tag_id,
                tag_name=tag.tag_name,
                description=tag.description,
                type=tag.type,
                color=tag.color,
                created_at=tag.createdAt,
                updated_at=tag.updatedAt,
                device_count=device_count,
                os_count=os_count,
                template_count=template_count,
                total_usage=device_count + os_count + template_count
            )

        except Exception as e:
            print(f"Error getting tag by id: {e}")
            return None

    async def get_tag_usage(self, tag_id: str) -> Optional[TagUsageResponse]:
        """ดึงข้อมูลการใช้งาน Tag โดยละเอียด"""
        try:
            tag = await self.prisma.tag.find_unique(
                where={"tag_id": tag_id},
                include={
                    "deviceNetworks": {
                        "select": {
                            "id": True,
                            "serial_number": True,
                            "device_name": True,
                            "device_model": True,
                            "type": True,
                            "status": True
                        }
                    },
                    "operatingSystems": {
                        "select": {
                            "id": True,
                            "os_name": True,
                            "os_type": True,
                            "description": True
                        }
                    },
                    "configurationTemplates": {
                        "select": {
                            "id": True,
                            "template_name": True,
                            "template_type": True,
                            "description": True
                        }
                    }
                }
            )

            if not tag:
                return None

            # แปลง Prisma objects เป็น dict
            device_networks = [dict(d) for d in tag.deviceNetworks] if tag.deviceNetworks else []
            operating_systems = [dict(o) for o in tag.operatingSystems] if tag.operatingSystems else []
            configuration_templates = [dict(t) for t in tag.configurationTemplates] if tag.configurationTemplates else []

            return TagUsageResponse(
                tag_id=tag.tag_id,
                tag_name=tag.tag_name,
                device_networks=device_networks,
                operating_systems=operating_systems,
                configuration_templates=configuration_templates,
                total_usage=len(device_networks) + len(operating_systems) + len(configuration_templates)
            )

        except Exception as e:
            print(f"Error getting tag usage: {e}")
            return None

    async def update_tag(
        self,
        tag_id: str,
        update_data: TagUpdate
    ) -> Optional[TagResponse]:
        """อัปเดต Tag"""
        try:
            # ตรวจสอบว่า tag มีอยู่หรือไม่
            existing_tag = await self.prisma.tag.find_unique(
                where={"tag_id": tag_id}
            )

            if not existing_tag:
                raise ValueError("ไม่พบ Tag ที่ต้องการอัปเดต")

            # เตรียมข้อมูลสำหรับอัปเดต
            update_dict: Dict[str, Any] = {}
            
            if update_data.tag_name is not None:
                # ตรวจสอบว่า tag_name ซ้ำหรือไม่
                if update_data.tag_name != existing_tag.tag_name:
                    duplicate = await self.prisma.tag.find_unique(
                        where={"tag_name": update_data.tag_name}
                    )
                    if duplicate:
                        raise ValueError(f"ชื่อ Tag '{update_data.tag_name}' มีอยู่ในระบบแล้ว")
                update_dict["tag_name"] = update_data.tag_name

            if update_data.description is not None:
                update_dict["description"] = update_data.description
            
            if update_data.type is not None:
                update_dict["type"] = update_data.type.value
            
            if update_data.color is not None:
                update_dict["color"] = update_data.color

            # ตรวจสอบว่ามีข้อมูลที่จะอัปเดตหรือไม่
            if not update_dict:
                raise ValueError("ไม่มีข้อมูลที่จะอัปเดต")

            # อัปเดตข้อมูล
            updated_tag = await self.prisma.tag.update(
                where={"tag_id": tag_id},
                data=update_dict,
                include={
                    "deviceNetworks": True,
                    "operatingSystems": True,
                    "configurationTemplates": True
                }
            )

            device_count = len(updated_tag.deviceNetworks) if updated_tag.deviceNetworks else 0
            os_count = len(updated_tag.operatingSystems) if updated_tag.operatingSystems else 0
            template_count = len(updated_tag.configurationTemplates) if updated_tag.configurationTemplates else 0

            return TagResponse(
                tag_id=updated_tag.tag_id,
                tag_name=updated_tag.tag_name,
                description=updated_tag.description,
                type=updated_tag.type,
                color=updated_tag.color,
                created_at=updated_tag.createdAt,
                updated_at=updated_tag.updatedAt,
                device_count=device_count,
                os_count=os_count,
                template_count=template_count,
                total_usage=device_count + os_count + template_count
            )

        except Exception as e:
            print(f"Error updating tag: {e}")
            if "ไม่พบ Tag" in str(e) or "มีอยู่ในระบบแล้ว" in str(e) or "ไม่มีข้อมูลที่จะอัปเดต" in str(e):
                raise e
            return None

    async def delete_tag(self, tag_id: str, force: bool = False) -> bool:
        """ลบ Tag"""
        try:
            # ตรวจสอบว่า tag มีอยู่หรือไม่
            existing_tag = await self.prisma.tag.find_unique(
                where={"tag_id": tag_id},
                include={
                    "deviceNetworks": True,
                    "operatingSystems": True,
                    "configurationTemplates": True
                }
            )

            if not existing_tag:
                raise ValueError("ไม่พบ Tag ที่ต้องการลบ")

            # นับการใช้งาน
            device_count = len(existing_tag.deviceNetworks) if existing_tag.deviceNetworks else 0
            os_count = len(existing_tag.operatingSystems) if existing_tag.operatingSystems else 0
            template_count = len(existing_tag.configurationTemplates) if existing_tag.configurationTemplates else 0
            total_usage = device_count + os_count + template_count

            # ตรวจสอบว่ามีการใช้งานหรือไม่
            if not force and total_usage > 0:
                usage_details = []
                if device_count > 0:
                    usage_details.append(f"{device_count} Device")
                if os_count > 0:
                    usage_details.append(f"{os_count} OS")
                if template_count > 0:
                    usage_details.append(f"{template_count} Template")
                
                raise ValueError(
                    f"ไม่สามารถลบ Tag นี้ได้ เนื่องจากกำลังถูกใช้งานโดย: {', '.join(usage_details)}"
                )

            # ลบ tag
            await self.prisma.tag.delete(
                where={"tag_id": tag_id}
            )

            return True

        except Exception as e:
            print(f"Error deleting tag: {e}")
            if "ไม่พบ Tag" in str(e) or "ไม่สามารถลบ Tag นี้ได้" in str(e):
                raise e
            return False

