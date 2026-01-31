from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
import os
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
    page_size: int = Query(8, ge=1, le=100, description="จำนวนรายการต่อหน้า"),
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
    template_name: str = Form(..., description="ชื่อ Template (ต้องไม่ซ้ำ)", min_length=1, max_length=200),
    description: Optional[str] = Form(None, description="คำอธิบาย Template", max_length=1000),
    template_type: str = Form("OTHER", description="ประเภทของ Template"),
    tag_name: Optional[str] = Form(None, description="Tag name ที่เชื่อมโยง"),
    config_content: Optional[str] = Form(None, description="เนื้อหา Config (Text)"),
    file: Optional[UploadFile] = File(None, description="ไฟล์ Config (.txt, .yaml, .yml)"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    template_svc: ConfigurationTemplateService = Depends(get_template_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์สร้าง Configuration Template ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        # Create request object manually
        try:
            template_enum = TemplateType(template_type)
        except ValueError:
             raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid template_type: {template_type}"
            )

        template_data = ConfigurationTemplateCreate(
            template_name=template_name,
            description=description,
            template_type=template_enum,
            tag_name=tag_name
        )
        
        # Determine detail content
        detail_text = config_content
        detail_filename = None
        detail_size = 0

        if file:
            # Validate file if provided
            allowed_extensions = {".txt", ".yaml", ".yml"}
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in allowed_extensions:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="อนุญาตเฉพาะไฟล์นามสกุล .txt, .yaml, .yml เท่านั้น"
                )
            
            try:
                content = await file.read()
                detail_text = content.decode("utf-8")
                detail_filename = file.filename
                detail_size = file.size
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ไฟล์ต้องเป็น Text encoding UTF-8 เท่านั้น"
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"ไม่สามารถอ่านไฟล์ได้: {str(e)}"
                )

        template = await template_svc.create_template(
            template_data,
            detail_content=detail_text,
            detail_filename=detail_filename,
            detail_size=detail_size
        )
        
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

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
import os

# ... imports ...

# ... existing code ...

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

@router.post("/{template_id}/upload", response_model=ConfigurationTemplateResponse)
async def upload_template_config(
    template_id: str,
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
    template_svc: ConfigurationTemplateService = Depends(get_template_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์อัปโหลด Config ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        # Validate file extension
        allowed_extensions = {".txt", ".yaml", ".yml"}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="อนุญาตเฉพาะไฟล์นามสกุล .txt, .yaml, .yml เท่านั้น"
            )

        # Read content
        try:
            content = await file.read()
            content_str = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ไฟล์ต้องเป็น Text encoding UTF-8 เท่านั้น"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ไม่สามารถอ่านไฟล์ได้: {str(e)}"
            )

        # Call service
        result = await template_svc.upload_config(template_id, content_str, file.filename, file.size)
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถบันทึกข้อมูล Config ได้"
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการอัปโหลด Config: {str(e)}"
        )

