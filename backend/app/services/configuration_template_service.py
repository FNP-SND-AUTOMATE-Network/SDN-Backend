from typing import Optional, List, Dict, Any
from app.models.configuration_template import (
    ConfigurationTemplateCreate,
    ConfigurationTemplateUpdate,
    ConfigurationTemplateResponse,
    ConfigurationTemplateDetailResponse,
    RelatedTagInfoTemplate
)

class ConfigurationTemplateService:
    #Service สำหรับจัดการ Configuration Template

    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def create_template(
        self, 
        template_data: ConfigurationTemplateCreate,
        detail_content: Optional[str] = None,
        detail_filename: Optional[str] = None,
        detail_size: Optional[int] = None
    ) -> Optional[ConfigurationTemplateResponse]:
        #สร้าง Configuration Template ใหม่
        try:
            # ตรวจสอบว่า template_name ซ้ำหรือไม่
            existing_template = await self.prisma.configurationtemplate.find_unique(
                where={"template_name": template_data.template_name}
            )
            if existing_template:
                raise ValueError(f"ชื่อ Template '{template_data.template_name}' มีอยู่ในระบบแล้ว")

            # Prepare creation data
            create_data = {
                "template_name": template_data.template_name,
                "description": template_data.description,
                "template_type": template_data.template_type.value
            }

            # Check and connect tags if provided (supports multiple tags)
            if template_data.tag_names:
                # Validate all tags exist
                tag_connects = []
                not_found_tags = []
                for tag_name in template_data.tag_names:
                    tag = await self.prisma.tag.find_unique(
                        where={"tag_name": tag_name}
                    )
                    if not tag:
                        not_found_tags.append(tag_name)
                    else:
                        tag_connects.append({"tag_name": tag_name})
                
                if not_found_tags:
                    raise ValueError(f"ไม่พบ Tag names: {', '.join(not_found_tags)}")
                
                # Connect all existing tags
                create_data["tags"] = {
                    "connect": tag_connects
                }

            # สร้าง Template
            template = await self.prisma.configurationtemplate.create(
                data=create_data,
                include={"tags": True, "deviceNetworks": True, "detail": True}
            )
            
            # ถ้ามี detail content หรือ file ให้สร้าง detail
            created_detail = None
            if detail_content or detail_filename:
                created_detail = await self.prisma.configurationtemplatedetail.create(
                    data={
                        "configuration_template_id": template.id,
                        "config_content": detail_content,
                        "file_name": detail_filename,
                        "file_size": detail_size if detail_size else 0
                    }
                )

            # แปลง tags เป็น list
            tags_info = []
            if template.tags:
                for tag in template.tags:
                    tags_info.append(RelatedTagInfoTemplate(
                        tag_id=tag.tag_id,
                        tag_name=tag.tag_name,
                        color=tag.color,
                        type=tag.type
                    ))
            
            # Prepare detail response
            detail_resp = None
            if created_detail:
                 detail_resp = ConfigurationTemplateDetailResponse(
                    id=created_detail.id,
                    config_content=created_detail.config_content,
                    file_name=created_detail.file_name,
                    file_size=created_detail.file_size,
                    updated_at=created_detail.updatedAt
                )

            return ConfigurationTemplateResponse(
                id=template.id,
                template_name=template.template_name,
                description=template.description,
                template_type=template.template_type,
                created_at=template.createdAt,
                updated_at=template.updatedAt,
                tags=tags_info,
                device_count=0,
                detail=detail_resp
            )

        except Exception as e:
            print(f"Error creating template: {e}")
            if "มีอยู่ในระบบแล้ว" in str(e):
                raise e
            return None

    async def get_templates(
        self,
        page: int = 1,
        page_size: int = 8,
        template_type: Optional[str] = None,
        search: Optional[str] = None,
        tag_name: Optional[str] = None,
        include_usage: bool = False
    ) -> tuple[List[ConfigurationTemplateResponse], int]:
        #ดึงรายการ Configuration Template ทั้งหมด
        try:
            where_conditions: Dict[str, Any] = {}
            
            if template_type:
                where_conditions["template_type"] = template_type
            
            if tag_name:
                where_conditions["tags"] = {
                    "some": {"tag_name": tag_name}
                }
            
            if search:
                where_conditions["OR"] = [
                    {"template_name": {"contains": search, "mode": "insensitive"}},
                    {"description": {"contains": search, "mode": "insensitive"}}
                ]

            total = await self.prisma.configurationtemplate.count(where=where_conditions)
            skip = (page - 1) * page_size
            
            include_options: Dict[str, Any] = {"tags": True, "detail": True}
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
                tags_info = []
                if template.tags:
                    for tag in template.tags:
                        tags_info.append(RelatedTagInfoTemplate(
                            tag_id=tag.tag_id,
                            tag_name=tag.tag_name,
                            color=tag.color,
                            type=tag.type
                        ))

                device_count = len(template.deviceNetworks) if hasattr(template, 'deviceNetworks') and template.deviceNetworks else 0
                
                detail_resp = None
                if template.detail:
                    detail_resp = ConfigurationTemplateDetailResponse(
                        id=template.detail.id,
                        config_content=template.detail.config_content,
                        file_name=template.detail.file_name,
                        file_size=template.detail.file_size,
                        updated_at=template.detail.updatedAt
                    )

                template_responses.append(ConfigurationTemplateResponse(
                    id=template.id,
                    template_name=template.template_name,
                    description=template.description,
                    template_type=template.template_type,
                    created_at=template.createdAt,
                    updated_at=template.updatedAt,
                    tags=tags_info,
                    device_count=device_count,
                    detail=detail_resp
                ))

            return template_responses, total

        except Exception as e:
            print(f"Error getting templates: {e}")
            return [], 0

    async def get_template_by_id(self, template_id: str, include_usage: bool = False) -> Optional[ConfigurationTemplateResponse]:
        #ดึงข้อมูล Configuration Template ตาม ID
        try:
            include_options: Dict[str, Any] = {"tags": True, "detail": True}
            if include_usage:
                include_options["deviceNetworks"] = True

            template = await self.prisma.configurationtemplate.find_unique(
                where={"id": template_id},
                include=include_options
            )

            if not template:
                return None

            tags_info = []
            if template.tags:
                for tag in template.tags:
                    tags_info.append(RelatedTagInfoTemplate(
                        tag_id=tag.tag_id,
                        tag_name=tag.tag_name,
                        color=tag.color,
                        type=tag.type
                    ))

            device_count = len(template.deviceNetworks) if hasattr(template, 'deviceNetworks') and template.deviceNetworks else 0

            detail_resp = None
            if template.detail:
                detail_resp = ConfigurationTemplateDetailResponse(
                    id=template.detail.id,
                    config_content=template.detail.config_content,
                    file_name=template.detail.file_name,
                    file_size=template.detail.file_size,
                    updated_at=template.detail.updatedAt
                )

            return ConfigurationTemplateResponse(
                id=template.id,
                template_name=template.template_name,
                description=template.description,
                template_type=template.template_type,
                created_at=template.createdAt,
                updated_at=template.updatedAt,
                tags=tags_info,
                device_count=device_count,
                detail=detail_resp
            )

        except Exception as e:
            print(f"Error getting template by id: {e}")
            return None

    async def update_template(self, template_id: str, update_data: ConfigurationTemplateUpdate) -> Optional[ConfigurationTemplateResponse]:
        #อัปเดต Configuration Template
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

            # Handle Tag update (supports multiple tags)
            if update_data.tag_names is not None:
                # If tag_names is empty list -> disconnect all tags
                if len(update_data.tag_names) == 0:
                    update_dict["tags"] = {"set": []}
                # If tag_names provided -> validate and set all tags
                else:
                    tag_sets = []
                    not_found_tags = []
                    for tag_name in update_data.tag_names:
                        tag = await self.prisma.tag.find_unique(
                            where={"tag_name": tag_name}
                        )
                        if not tag:
                            not_found_tags.append(tag_name)
                        else:
                            tag_sets.append({"tag_name": tag_name})
                    
                    if not_found_tags:
                        raise ValueError(f"ไม่พบ Tag names: {', '.join(not_found_tags)}")
                    
                    # Use "set" to replace all existing tags with new ones
                    update_dict["tags"] = {"set": tag_sets}

            if not update_dict:
                raise ValueError("ไม่มีข้อมูลที่จะอัปเดต")

            updated_template = await self.prisma.configurationtemplate.update(
                where={"id": template_id},
                data=update_dict,
                include={
                    "tags": True,
                    "deviceNetworks": True,
                    "detail": True
                }
            )

            tags_info = []
            if updated_template.tags:
                for tag in updated_template.tags:
                    tags_info.append(RelatedTagInfoTemplate(
                        tag_id=tag.tag_id,
                        tag_name=tag.tag_name,
                        color=tag.color,
                        type=tag.type
                    ))

            device_count = len(updated_template.deviceNetworks) if updated_template.deviceNetworks else 0

            detail_resp = None
            if updated_template.detail:
                detail_resp = ConfigurationTemplateDetailResponse(
                    id=updated_template.detail.id,
                    config_content=updated_template.detail.config_content,
                    file_name=updated_template.detail.file_name,
                    file_size=updated_template.detail.file_size,
                    updated_at=updated_template.detail.updatedAt
                )

            return ConfigurationTemplateResponse(
                id=updated_template.id,
                template_name=updated_template.template_name,
                description=updated_template.description,
                template_type=updated_template.template_type,
                created_at=updated_template.createdAt,
                updated_at=updated_template.updatedAt,
                tags=tags_info,
                device_count=device_count,
                detail=detail_resp
            )

        except Exception as e:
            print(f"Error updating template: {e}")
            if "ไม่พบ" in str(e) or "มีอยู่ในระบบแล้ว" in str(e) or "ไม่มีข้อมูลที่จะอัปเดต" in str(e):
                raise e
            return None

    async def delete_template(self, template_id: str, force: bool = False) -> bool:
        #ลบ Configuration Template
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

    async def upload_config(self, template_id: str, content: str, filename: str, file_size: int) -> Optional[ConfigurationTemplateResponse]:
        #อัปโหลด Configuration content
        try:
            # Check if template exists
            template = await self.prisma.configurationtemplate.find_unique(
                where={"id": template_id},
                include={"detail": True}
            )

            if not template:
                raise ValueError("ไม่พบ Configuration Template")

            # Upsert detail
            if template.detail:
                # Update existing
                await self.prisma.configurationtemplatedetail.update(
                    where={"id": template.detail.id},
                    data={
                        "config_content": content,
                        "file_name": filename,
                        "file_size": file_size
                    }
                )
            else:
                # Create new
                await self.prisma.configurationtemplatedetail.create(
                    data={
                        "configuration_template_id": template_id,
                        "config_content": content,
                        "file_name": filename,
                        "file_size": file_size
                    }
                )

            return await self.get_template_by_id(template_id)

        except Exception as e:
            print(f"Error uploading config: {e}")
            raise e
