from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.backup_service import BackupService
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

@router.get("/", response_model=BackupListResponse)
async def get_backups(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by backup_name, description"),
    policy_id: Optional[str] = Query(None, description="Filter by Policy ID"),
    os_id: Optional[str] = Query(None, description="Filter by OS ID"),
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
            policy_id=policy_id,
            os_id=os_id,
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
    backup_data: BackupCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to create a backup"
            )

        backup = await backup_svc.create_backup(backup_data)
        
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error in create_backup"
            )

        return BackupCreateResponse(
            message="Backup created successfully",
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
            detail=f"Error in create_backup: {str(e)}"
        )

@router.put("/{backup_id}", response_model=BackupUpdateResponse)
async def update_backup(
    backup_id: str,
    update_data: BackupUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update a backup"
            )

        backup = await backup_svc.update_backup(backup_id, update_data)
        
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error in update_backup"
            )

        return BackupUpdateResponse(
            message="Backup updated successfully",
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
            detail=f"Error in update_backup: {str(e)}"
        )

@router.delete("/{backup_id}", response_model=BackupDeleteResponse)
async def delete_backup(
    backup_id: str,
    force: bool = Query(False, description="Force delete even if in use"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    backup_svc: BackupService = Depends(get_backup_service)
):
    try:
        if force:
            if current_user["role"] != "OWNER":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to delete a backup"
                )
        else:
            if current_user["role"] not in ["ADMIN", "OWNER"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to delete a backup"
                )

        success = await backup_svc.delete_backup(backup_id, force=force)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error in delete_backup"
            )

        return BackupDeleteResponse(
            message="Backup deleted successfully"
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

