from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.backup_service import BackupService
from app.services.audit_service import AuditService
from app.models.audit import AuditAction
import logging

logger = logging.getLogger(__name__)
from app.models.backup import (
    BackupCreate,
    BackupUpdate,
    BackupResponse,
    BackupListResponse,
    BackupCreateResponse,
    BackupUpdateResponse,
    BackupDeleteResponse,
    BackupStatus
)
from prisma import Prisma

router = APIRouter(prefix="/backups", tags=["Backups"])

def get_backup_service(db: Prisma = Depends(get_db)) -> BackupService:
    return BackupService(db)

def get_audit_service(db: Prisma = Depends(get_db)) -> AuditService:
    return AuditService(db)

@router.get("/", response_model=BackupListResponse)
async def get_backups(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by backup_name, description"),
    auto_backup: Optional[bool] = Query(None, description="Filter by auto_backup"),
    include_usage: bool = Query(False, description="Include usage count"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service)
):
    try:
        backups, total = await backup_svc.get_backups(
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            auto_backup=auto_backup,
            include_usage=include_usage
        )

        return BackupListResponse(
            total=total,
            page=page,
            page_size=page_size,
            backups=backups
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error in get_backups: {str(e)}"
        )

@router.get("/{backup_id}", response_model=BackupResponse)
async def get_backup(
    backup_id: str,
    include_usage: bool = Query(False, description="Include usage count"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service)
):
    try:
        backup = await backup_svc.get_backup_by_id(backup_id, include_usage=include_usage)
        
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Backup not found"
            )
        
        return backup

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error in get_backup: {str(e)}"
        )

@router.post("/", response_model=BackupCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_backup(
    request: Request,
    backup_data: BackupCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to manage backup profiles."
            )

        backup = await backup_svc.create_backup(backup_data, current_user["id"])
        
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create the backup profile due to an internal error."
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_backup_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.BACKUP_PROFILE_CREATE,
                backup_id=backup.id,
                backup_name=backup.backup_name,
                changes=backup_data.dict(exclude_unset=True),
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return BackupCreateResponse(
            message="Backup profile created and scheduled successfully.",
            backup=backup
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
            detail=f"An unexpected error occurred while processing the backup creation: {str(e)}"
        )

@router.put("/{backup_id}", response_model=BackupUpdateResponse)
async def update_backup(
    request: Request,
    backup_id: str,
    update_data: BackupUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update a backup profile."
            )

        backup = await backup_svc.update_backup(backup_id, update_data)
        
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update the backup profile due to an internal error."
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_backup_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.BACKUP_PROFILE_UPDATE,
                backup_id=backup.id,
                backup_name=backup.backup_name,
                changes=update_data.dict(exclude_unset=True),
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return BackupUpdateResponse(
            message="Backup profile updated and schedule refreshed successfully.",
            backup=backup
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
            detail=f"An unexpected error occurred while updating the backup profile: {str(e)}"
        )

@router.delete("/{backup_id}", response_model=BackupDeleteResponse)
async def delete_backup(
    request: Request,
    backup_id: str,
    force: bool = Query(False, description="Force delete even if in use"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        if force:
            if current_user["role"] != "OWNER":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to force delete a backup profile."
                )
        else:
            if current_user["role"] not in ["ADMIN", "OWNER"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to delete a backup profile."
                )
        
        old_backup = await backup_svc.get_backup_by_id(backup_id)
        if not old_backup:
            raise HTTPException(status_code=404, detail="Backup not found")

        success = await backup_svc.delete_backup(backup_id, force=force)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete the backup profile due to an internal error."
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_backup_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.BACKUP_PROFILE_DELETE,
                backup_id=backup_id,
                backup_name=old_backup.backup_name,
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return BackupDeleteResponse(
            message="Backup profile and associated schedule deleted successfully."
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
            detail=f"Error in delete_backup: {str(e)}"
        )

@router.put("/{backup_id}/pause", response_model=BackupUpdateResponse)
async def pause_backup(
    request: Request,
    backup_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to pause a backup profile."
            )

        backup = await backup_svc.pause_backup(backup_id)
        
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to pause the backup profile."
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_backup_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.BACKUP_PROFILE_PAUSE,
                backup_id=backup.id,
                backup_name=backup.backup_name,
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return BackupUpdateResponse(
            message="Backup profile paused successfully.",
            backup=backup
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
            detail=f"An unexpected error occurred: {str(e)}"
        )

@router.put("/{backup_id}/reactivate", response_model=BackupUpdateResponse)
async def reactivate_backup(
    request: Request,
    backup_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to reactivate a backup profile."
            )

        backup = await backup_svc.reactivate_backup(backup_id)
        
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reactivate the backup profile."
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_backup_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.BACKUP_PROFILE_RESUME,
                backup_id=backup.id,
                backup_name=backup.backup_name,
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return BackupUpdateResponse(
            message="Backup profile reactivated successfully.",
            backup=backup
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
            detail=f"An unexpected error occurred: {str(e)}"
        )

