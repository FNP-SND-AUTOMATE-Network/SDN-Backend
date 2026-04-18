from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.local_site_service import LocalSiteService
from app.models.local_site import (
    LocalSiteCreate,
    LocalSiteUpdate,
    LocalSiteResponse,
    LocalSiteListResponse,
    LocalSiteCreateResponse,
    LocalSiteUpdateResponse,
    LocalSiteDeleteResponse,
    SiteType
)
from prisma import Prisma
from app.services.audit_service import AuditService
from app.models.audit import AuditAction
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/local-sites", tags=["Local Sites"])

def get_local_site_service(db: Prisma = Depends(get_db)) -> LocalSiteService:
    return LocalSiteService(db)

def get_audit_service(db = Depends(get_db)):
    return AuditService(db)

@router.get("/", response_model=LocalSiteListResponse)
async def get_local_sites(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    site_type: Optional[str] = Query(None, description="Filter by site type"),
    search: Optional[str] = Query(None, description="Search by site_code, site_name, address, city"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    local_site_svc: LocalSiteService = Depends(get_local_site_service)
):
    try:
        sites, total = await local_site_svc.get_local_sites(
            page=page,
            page_size=page_size,
            site_type=site_type,
            search=search
        )

        return LocalSiteListResponse(
            total=total,
            page=page,
            page_size=page_size,
            sites=sites
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching local sites: {str(e)}"
        )

@router.get("/{site_id}", response_model=LocalSiteResponse)
async def get_local_site(
    site_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    local_site_svc: LocalSiteService = Depends(get_local_site_service)
):
    try:
        site = await local_site_svc.get_local_site_by_id(site_id)
        
        if not site:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Local site not found"
            )
        
        return site

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching local site: {str(e)}"
        )

@router.post("/", response_model=LocalSiteCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_local_site(
    request: Request,
    site_data: LocalSiteCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    local_site_svc: LocalSiteService = Depends(get_local_site_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ENGINEER ขึ้นไป)
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to create local site"
            )

        site = await local_site_svc.create_local_site(site_data)
        
        if not site:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error creating local site"
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_generic_system_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.SITE_CREATE,
                entity_type="SITE",
                entity_id=site.id,
                entity_name=site.site_name,
                changes=site_data.dict(exclude_unset=True),
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return LocalSiteCreateResponse(
            message="Local site created successfully",
            site=site
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
            detail=f"Error creating local site: {str(e)}"
        )

@router.put("/{site_id}", response_model=LocalSiteUpdateResponse)
async def update_local_site(
    request: Request,
    site_id: str,
    update_data: LocalSiteUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    local_site_svc: LocalSiteService = Depends(get_local_site_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ENGINEER ขึ้นไป)
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update local site"
            )

        site = await local_site_svc.update_local_site(site_id, update_data)
        
        if not site:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error updating local site"
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_generic_system_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.SITE_UPDATE,
                entity_type="SITE",
                entity_id=site.id,
                entity_name=site.site_name,
                changes=update_data.dict(exclude_unset=True),
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return LocalSiteUpdateResponse(
            message="Local site updated successfully",
            site=site
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
            detail=f"Error updating local site: {str(e)}"
        )

@router.delete("/{site_id}", response_model=LocalSiteDeleteResponse)
async def delete_local_site(
    request: Request,
    site_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    local_site_svc: LocalSiteService = Depends(get_local_site_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        # ตรวจสอบสิทธิ์ (ต้องเป็น ADMIN หรือ OWNER)
        if current_user["role"] not in ["ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete local site"
            )

        old_site = await local_site_svc.get_local_site_by_id(site_id)
        if not old_site:
            raise HTTPException(status_code=404, detail="Local site not found")

        success = await local_site_svc.delete_local_site(site_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error deleting local site"
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_generic_system_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.SITE_DELETE,
                entity_type="SITE",
                entity_id=site_id,
                entity_name=old_site.site_name,
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return LocalSiteDeleteResponse(
            message="Local site deleted successfully"
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
            detail=f"Error deleting local site: {str(e)}"
        )

