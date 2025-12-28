from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.configuration_template_service import ConfigurationTemplateService
from app.models.configuration_template import (
    ConfigurationTemplateCreate,
    ConfigurationTemplateUpdate,
    ConfigurationTemplateResponse,
    ConfigurationTemplateListResponse,
    ConfigurationTemplateCreateResponse,
    ConfigurationTemplateUpdateResponse,
    ConfigurationTemplateDeleteResponse,
    TemplateType
)
from prisma import Prisma

router = APIRouter(prefix="/configuration-templates", tags=["Configuration Templates"])

def get_template_service(db: Prisma = Depends(get_db)) -> ConfigurationTemplateService:
    return ConfigurationTemplateService(db)

@router.get("/", response_model=ConfigurationTemplateListResponse)
async def get_templates(
    page: int = Query(1, ge=1, description="หน้าที่ต้องการ"),
    page_size: int = Query(20, ge=1, le=100, description="จำนวนรายการต่อหน้า"),
    template_type: Optional[str] = Query(None, description="กรองตามประเภท Template"),
    search: Optional[str] = Query(None, description="ค้นหาจาก template_name, description"),
    tag_name: Optional[str] = Query(None, description="กรองตาม Tag name"),
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    template_svc: ConfigurationTemplateService = Depends(get_template_service)
):
    try:
        templates, total = await template_svc.get_templates(
            page=page,
            page_size=page_size,
            template_type=template_type,
            search=search,
            tag_name=tag_name,
            include_usage=include_usage
        )

        return ConfigurationTemplateListResponse(
            total=total,
            page=page,
            page_size=page_size,
            templates=templates
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงรายการ Configuration Template: {str(e)}"
        )

@router.get("/{template_id}", response_model=ConfigurationTemplateResponse)
async def get_template(
    template_id: str,
    include_usage: bool = Query(False, description="รวมจำนวนการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    template_svc: ConfigurationTemplateService = Depends(get_template_service)
):
    try:
        template = await template_svc.get_template_by_id(template_id, include_usage=include_usage)
        
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ Configuration Template ที่ต้องการ"
            )
        
        return template

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการดึงข้อมูล Configuration Template: {str(e)}"
        )

@router.post("/", response_model=ConfigurationTemplateCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    template_data: ConfigurationTemplateCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    template_svc: ConfigurationTemplateService = Depends(get_template_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์สร้าง Configuration Template ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        template = await template_svc.create_template(template_data)
        
        if not template:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถสร้าง Configuration Template ได้"
            )

        return ConfigurationTemplateCreateResponse(
            message="สร้าง Configuration Template สำเร็จ",
            template=template
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการสร้าง Configuration Template: {str(e)}"
        )

@router.put("/{template_id}", response_model=ConfigurationTemplateUpdateResponse)
async def update_template(
    template_id: str,
    update_data: ConfigurationTemplateUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    template_svc: ConfigurationTemplateService = Depends(get_template_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์แก้ไข Configuration Template ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        template = await template_svc.update_template(template_id, update_data)
        
        if not template:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถอัปเดต Configuration Template ได้"
            )

        return ConfigurationTemplateUpdateResponse(
            message="อัปเดต Configuration Template สำเร็จ",
            template=template
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการอัปเดต Configuration Template: {str(e)}"
        )

@router.delete("/{template_id}", response_model=ConfigurationTemplateDeleteResponse)
async def delete_template(
    template_id: str,
    force: bool = Query(False, description="บังคับลบแม้มีการใช้งาน"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    template_svc: ConfigurationTemplateService = Depends(get_template_service)
):
    try:
        if force:
            if current_user["role"] != "OWNER":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="การลบแบบบังคับต้องเป็น OWNER เท่านั้น"
                )
        else:
            if current_user["role"] not in ["ADMIN", "OWNER"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="ไม่มีสิทธิ์ลบ Configuration Template ต้องเป็น ADMIN หรือ OWNER"
                )

        success = await template_svc.delete_template(template_id, force=force)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถลบ Configuration Template ได้"
            )

        return ConfigurationTemplateDeleteResponse(
            message="ลบ Configuration Template สำเร็จ"
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการลบ Configuration Template: {str(e)}"
        )

