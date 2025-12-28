from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.tag_service import TagService
from app.models.tag import (
    TagCreate,
    TagUpdate,
    TagResponse,
    TagListResponse,
    TagCreateResponse,
    TagUpdateResponse,
    TagDeleteResponse,
    TagUsageResponse
)
from prisma import Prisma

router = APIRouter(prefix="/tags", tags=["Tags"])

def get_tag_service(db: Prisma = Depends(get_db)) -> TagService:
    return TagService(db)

@router.get("/", response_model=TagListResponse)
async def get_tags(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=500, description="Number of items per page"),
    search: Optional[str] = Query(None, description="Search by tag_name, description"),
    include_usage: bool = Query(False, description="Include usage count"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    try:
        tags, total = await tag_svc.get_tags(
            page=page,
            page_size=page_size,
            search=search,
            include_usage=include_usage
        )

        return TagListResponse(
            total=total,
            page=page,
            page_size=page_size,
            tags=tags
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting tags: {str(e)}"
        )

@router.get("/{tag_id}", response_model=TagResponse)
async def get_tag(
    tag_id: str,
    include_usage: bool = Query(False, description="Include usage count"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    try:
        tag = await tag_svc.get_tag_by_id(tag_id, include_usage=include_usage)
        
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found"
            )
        
        return tag

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting tag: {str(e)}"
        )

@router.get("/{tag_id}/usage", response_model=TagUsageResponse)
async def get_tag_usage(
    tag_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    try:
        usage = await tag_svc.get_tag_usage(tag_id)
        
        if not usage:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found"
            )
        
        return usage

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting tag usage: {str(e)}"
        )

@router.post("/", response_model=TagCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    tag_data: TagCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ENGINEER ขึ้นไป)
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ไม่มีสิทธิ์สร้าง Tag ต้องเป็น ENGINEER, ADMIN หรือ OWNER"
            )

        tag = await tag_svc.create_tag(tag_data)
        
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error creating tag"
            )

        return TagCreateResponse(
            message="Tag created successfully",
            tag=tag
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
            detail=f"Error creating tag: {str(e)}"
        )

@router.put("/{tag_id}", response_model=TagUpdateResponse)
async def update_tag(
    tag_id: str,
    update_data: TagUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ENGINEER ขึ้นไป)
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update tag"
            )

        tag = await tag_svc.update_tag(tag_id, update_data)
        
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error updating tag"
            )

        return TagUpdateResponse(
            message="Tag updated successfully",
            tag=tag
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
            detail=f"Error updating tag: {str(e)}"
        )

@router.delete("/{tag_id}", response_model=TagDeleteResponse)
async def delete_tag(
    tag_id: str,
    force: bool = Query(False, description="Force delete even if in use (use with caution)"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    tag_svc: TagService = Depends(get_tag_service)
):
    try:
        # ตรวจสอบสิทธิ์
        if force:
            # บังคับลบต้องเป็น OWNER เท่านั้น
            if current_user["role"] != "OWNER":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Force delete must be performed by OWNER"
                )
        else:
            # ลบปกติต้องเป็น ADMIN หรือ OWNER
            if current_user["role"] not in ["ADMIN", "OWNER"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to delete tag"
                )

        success = await tag_svc.delete_tag(tag_id, force=force)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error deleting tag"
            )

        return TagDeleteResponse(
            message="Tag deleted successfully"
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
            detail=f"Error deleting tag: {str(e)}"
        )

