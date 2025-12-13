from typing import Optional, List, Dict, Any
from app.models.configuration_template import (
    ConfigurationTemplateCreate,
    ConfigurationTemplateUpdate,
    ConfigurationTemplateResponse,
    RelatedTagInfoTemplate
)

class ConfigurationTemplateService:
    """Service สำหรับจัดการ Configuration Template"""

    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def create_template(self, template_data: ConfigurationTemplateCreate) -> Optional[ConfigurationTemplateResponse]:
        """สร้าง Configuration Template ใหม่"""
        try:
            # ตรวจสอบว่า template_name ซ้ำหรือไม่
            existing_template = await self.prisma.configurationtemplate.find_unique(
                where={"template_name": template_data.template_name}
            )
            if existing_template:
                raise ValueError(f"ชื่อ Template '{template_data.template_name}' มีอยู่ในระบบแล้ว")

            # ถ้ามี tag_name ให้ตรวจสอบว่ามีอยู่จริง
            if template_data.tag_name:
                tag = await self.prisma.tag.find_unique(
                    where={"tag_name": template_data.tag_name}
                )
                if not tag:
                    raise ValueError(f"ไม่พบ Tag name: {template_data.tag_name}")

            # สร้าง Template
            template = await self.prisma.configurationtemplate.create(
                data={
                    "template_name": template_data.template_name,
                    "description": template_data.description,
                    "template_type": template_data.template_type.value,
                    "tag_name": template_data.tag_name
                },
                include={"tag": True}
            )

            tag_info = None
            if template.tag:
                tag_info = RelatedTagInfoTemplate(
                    tag_id=template.tag.tag_id,
                    tag_name=template.tag.tag_name,
                    color=template.tag.color,
                    type=template.tag.type
                )

            return ConfigurationTemplateResponse(
                id=template.id,
                template_name=template.template_name,
                description=template.description,
                template_type=template.template_type,
                tag_name=template.tag_name,
                created_at=template.createdAt,
                updated_at=template.updatedAt,
                tag=tag_info,
                device_count=0
            )

        except Exception as e:
            print(f"Error creating template: {e}")
            if "มีอยู่ในระบบแล้ว" in str(e) or "ไม่พบ Tag" in str(e):
                raise e
            return None

    async def get_templates(
        self,
        page: int = 1,
        page_size: int = 20,
        template_type: Optional[str] = None,
        search: Optional[str] = None,
        tag_name: Optional[str] = None,
        include_usage: bool = False
    ) -> tuple[List[ConfigurationTemplateResponse], int]:
        """ดึงรายการ Configuration Template ทั้งหมด"""
        try:
            where_conditions: Dict[str, Any] = {}
            
            if template_type:
                where_conditions["template_type"] = template_type
            
            if tag_name:
                where_conditions["tag_name"] = tag_name
            
            if search:
                where_conditions["OR"] = [
                    {"template_name": {"contains": search, "mode": "insensitive"}},
                    {"description": {"contains": search, "mode": "insensitive"}}
                ]

            total = await self.prisma.configurationtemplate.count(where=where_conditions)
            skip = (page - 1) * page_size
            
            include_options: Dict[str, Any] = {"tag": True}
            if include_usage:
                include_options["deviceNetworks"] = True

            templates = await self.prisma.configurationtemplate.find_many(
                where=where_conditions,
                skip=skip,
                take=page_size,
                order={"createdAt": "desc"},
                include=include_options
            )

            template_responses = []
            for template in templates:
                tag_info = None
                if template.tag:
                    tag_info = RelatedTagInfoTemplate(
                        tag_id=template.tag.tag_id,
                        tag_name=template.tag.tag_name,
                        color=template.tag.color,
                        type=template.tag.type
                    )

                device_count = len(template.deviceNetworks) if hasattr(template, 'deviceNetworks') and template.deviceNetworks else 0
                
                template_responses.append(ConfigurationTemplateResponse(
                    id=template.id,
                    template_name=template.template_name,
                    description=template.description,
                    template_type=template.template_type,
                    tag_name=template.tag_name,
                    created_at=template.createdAt,
                    updated_at=template.updatedAt,
                    tag=tag_info,
                    device_count=device_count
                ))

            return template_responses, total

        except Exception as e:
            print(f"Error getting templates: {e}")
            return [], 0

    async def get_template_by_id(self, template_id: str, include_usage: bool = False) -> Optional[ConfigurationTemplateResponse]:
        """ดึงข้อมูล Configuration Template ตาม ID"""
        try:
            include_options: Dict[str, Any] = {"tag": True}
            if include_usage:
                include_options["deviceNetworks"] = True

            template = await self.prisma.configurationtemplate.find_unique(
                where={"id": template_id},
                include=include_options
            )

            if not template:
                return None

            tag_info = None
            if template.tag:
                tag_info = RelatedTagInfoTemplate(
                    tag_id=template.tag.tag_id,
                    tag_name=template.tag.tag_name,
                    color=template.tag.color,
                    type=template.tag.type
                )

            device_count = len(template.deviceNetworks) if hasattr(template, 'deviceNetworks') and template.deviceNetworks else 0

            return ConfigurationTemplateResponse(
                id=template.id,
                template_name=template.template_name,
                description=template.description,
                template_type=template.template_type,
                tag_name=template.tag_name,
                created_at=template.createdAt,
                updated_at=template.updatedAt,
                tag=tag_info,
                device_count=device_count
            )

        except Exception as e:
            print(f"Error getting template by id: {e}")
            return None

    async def update_template(self, template_id: str, update_data: ConfigurationTemplateUpdate) -> Optional[ConfigurationTemplateResponse]:
        """อัปเดต Configuration Template"""
        try:
            existing_template = await self.prisma.configurationtemplate.find_unique(
                where={"id": template_id}
            )

            if not existing_template:
                raise ValueError("ไม่พบ Configuration Template ที่ต้องการอัปเดต")

            update_dict: Dict[str, Any] = {}
            
            if update_data.template_name is not None:
                if update_data.template_name != existing_template.template_name:
                    duplicate = await self.prisma.configurationtemplate.find_unique(
                        where={"template_name": update_data.template_name}
                    )
                    if duplicate:
                        raise ValueError(f"ชื่อ Template '{update_data.template_name}' มีอยู่ในระบบแล้ว")
                update_dict["template_name"] = update_data.template_name

            if update_data.description is not None:
                update_dict["description"] = update_data.description
            
            if update_data.template_type is not None:
                update_dict["template_type"] = update_data.template_type.value
            
            if update_data.tag_name is not None:
                if update_data.tag_name:
                    tag = await self.prisma.tag.find_unique(
                        where={"tag_name": update_data.tag_name}
                    )
                    if not tag:
                        raise ValueError(f"ไม่พบ Tag name: {update_data.tag_name}")
                update_dict["tag_name"] = update_data.tag_name

            if not update_dict:
                raise ValueError("ไม่มีข้อมูลที่จะอัปเดต")

            updated_template = await self.prisma.configurationtemplate.update(
                where={"id": template_id},
                data=update_dict,
                include={
                    "tag": True,
                    "deviceNetworks": True
                }
            )

            tag_info = None
            if updated_template.tag:
                tag_info = RelatedTagInfoTemplate(
                    tag_id=updated_template.tag.tag_id,
                    tag_name=updated_template.tag.tag_name,
                    color=updated_template.tag.color,
                    type=updated_template.tag.type
                )

            device_count = len(updated_template.deviceNetworks) if updated_template.deviceNetworks else 0

            return ConfigurationTemplateResponse(
                id=updated_template.id,
                template_name=updated_template.template_name,
                description=updated_template.description,
                template_type=updated_template.template_type,
                tag_name=updated_template.tag_name,
                created_at=updated_template.createdAt,
                updated_at=updated_template.updatedAt,
                tag=tag_info,
                device_count=device_count
            )

        except Exception as e:
            print(f"Error updating template: {e}")
            if "ไม่พบ" in str(e) or "มีอยู่ในระบบแล้ว" in str(e) or "ไม่มีข้อมูลที่จะอัปเดต" in str(e):
                raise e
            return None

    async def delete_template(self, template_id: str, force: bool = False) -> bool:
        """ลบ Configuration Template"""
        try:
            existing_template = await self.prisma.configurationtemplate.find_unique(
                where={"id": template_id},
                include={"deviceNetworks": True}
            )

            if not existing_template:
                raise ValueError("ไม่พบ Configuration Template ที่ต้องการลบ")

            device_count = len(existing_template.deviceNetworks) if existing_template.deviceNetworks else 0

            if not force and device_count > 0:
                raise ValueError(
                    f"ไม่สามารถลบ Template นี้ได้ เนื่องจากกำลังถูกใช้งานโดย {device_count} Device"
                )

            await self.prisma.configurationtemplate.delete(where={"id": template_id})
            return True

        except Exception as e:
            print(f"Error deleting template: {e}")
            if "ไม่พบ Configuration Template" in str(e) or "ไม่สามารถลบ Template นี้ได้" in str(e):
                raise e
            return False

