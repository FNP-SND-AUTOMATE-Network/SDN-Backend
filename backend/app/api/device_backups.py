from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime

# You will need to import your database dependency `get_prisma` or similar
from app.database import get_db
from app.services.device_backup_service import DeviceBackupService
from app.api.users import get_current_user
from prisma.enums import ConfigType, BackupJobStatus

router = APIRouter(
    prefix="/api/v1/devices/backups",
    tags=["Device Backups"]
)

# --- Pydantic Models for Requests and Responses ---
class BulkBackupRequest(BaseModel):
    device_ids: List[str]
    backup_profile_id: Optional[str] = None
    config_type: ConfigType = ConfigType.RUNNING

class BackupTriggerResponse(BaseModel):
    message: str
    job_info: dict

class DeviceBackupRecordResponse(BaseModel):
    id: str
    device_id: str
    backup_profile_id: Optional[str]
    config_type: str
    config_format: str
    status: str
    error_message: Optional[str]
    file_size: Optional[int]
    file_hash: Optional[str]
    triggered_by_user: Optional[str]
    created_at: datetime
    updated_at: datetime
    # Omitting 'config_content' from the list view to save bandwidth

class BackupDiffRequest(BaseModel):
    record_id_1: str
    record_id_2: str

class BackupDiffResponse(BaseModel):
    diff_output: str

class BackupStatsResponse(BaseModel):
    total_devices_with_backup: int
    last_success: int
    last_failed: int
    in_progress: int

# --- API Endpoints ---

@router.get("/stats/summary", response_model=BackupStatsResponse)
async def get_backup_stats_summary(
    current_user: dict = Depends(get_current_user),
    prisma=Depends(get_db)
):
    """
    Get backup statistics. Returns the count of devices based on their LATEST backup status.
    """
    query = '''
        SELECT status, count(*) as count 
        FROM (
            SELECT DISTINCT ON (device_id) status 
            FROM "DeviceBackupRecord" 
            ORDER BY device_id, "createdAt" DESC
        ) as latest_backups
        GROUP BY status;
    '''
    
    results = await prisma.query_raw(query)
    
    stats = {
        "SUCCESS": 0,
        "FAILED": 0,
        "IN_PROGRESS": 0
    }
    
    total = 0
    for row in results:
        status_val = row.get("status") if isinstance(row, dict) else getattr(row, "status", None)
        count_val = row.get("count", 0) if isinstance(row, dict) else getattr(row, "count", 0)
        
        if status_val in stats:
            stats[status_val] = int(count_val)
        total += int(count_val)
        
    return BackupStatsResponse(
        total_devices_with_backup=total,
        last_success=stats["SUCCESS"],
        last_failed=stats["FAILED"],
        in_progress=stats["IN_PROGRESS"]
    )

@router.post("", response_model=BackupTriggerResponse, status_code=202)
async def trigger_bulk_backup(
    payload: BulkBackupRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    prisma=Depends(get_db)
):
    """
    Trigger an asynchronous backup job for multiple devices.
    Returns 202 Accepted immediately with the created Record IDs for tracking.
    """
    if not payload.device_ids:
        raise HTTPException(status_code=400, detail="device_ids list cannot be empty")

    service = DeviceBackupService(prisma)

    # Extract user ID from the dictionary returned by get_current_user
    user_id = current_user.get("id")

    # 1. Create IN_PROGRESS records upfront so the user can track them immediately
    try:
        pending_records = await service.create_pending_records(
            device_ids=payload.device_ids,
            user_id=user_id,
            backup_profile_id=payload.backup_profile_id,
            config_type=payload.config_type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create tracking records: {str(e)}")

    record_ids = [rec.id for rec in pending_records]

    # 2. Inject the heavy lifting into background task
    background_tasks.add_task(
        service.execute_bulk_backups_background,
        records=pending_records,
        user_id=user_id,
        config_type=payload.config_type
    )

    return BackupTriggerResponse(
        message="Backup process started in the background.",
        job_info={
            "device_count": len(payload.device_ids),
            "record_ids": record_ids
        }
    )

@router.get("/device/{device_id}", response_model=List[DeviceBackupRecordResponse])
async def get_device_backup_history(
    device_id: str,
    limit: int = Query(20, ge=1, le=100),
    page: int = Query(1, ge=1),
    prisma=Depends(get_db)
):
    """
    Get the backup history for a specific device. 
    Does not include the full config_content to keep responses fast.
    """
    skip = (page - 1) * limit
    
    records = await prisma.devicebackuprecord.find_many(
        where={"device_id": device_id},
        order={"createdAt": "desc"},
        skip=skip,
        take=limit
    )

    # Convert Prisma models to Pydantic responses manually here or use Model.model_validate
    return [
        DeviceBackupRecordResponse(
            id=r.id,
            device_id=r.device_id,
            backup_profile_id=r.backup_profile_id,
            config_type=r.config_type,
            config_format=r.config_format,
            status=r.status,
            error_message=r.error_message,
            file_size=r.file_size,
            file_hash=r.file_hash,
            triggered_by_user=r.triggered_by_user,
            created_at=r.createdAt,
            updated_at=r.updatedAt
        ) for r in records
    ]

@router.get("/{record_id}")
async def get_backup_record_details(
    record_id: str,
    prisma=Depends(get_db)
):
    """
    Get the full details of a specific backup record, INCLUDING the raw configuration content.
    """
    record = await prisma.devicebackuprecord.find_unique(where={"id": record_id})
    if not record:
        raise HTTPException(status_code=404, detail="Backup record not found")
        
    return record # Returning raw prisma dict (FastAPI handles it) or you can create a full Pydantic model

@router.post("/diff", response_model=BackupDiffResponse)
async def compare_backup_records(
    payload: BackupDiffRequest,
    prisma=Depends(get_db)
):
    """
    Compare two configuration backup records and return the unified diff.
    """
    record1 = await prisma.devicebackuprecord.find_unique(where={"id": payload.record_id_1})
    record2 = await prisma.devicebackuprecord.find_unique(where={"id": payload.record_id_2})

    if not record1:
        raise HTTPException(status_code=404, detail=f"Record 1 ({payload.record_id_1}) not found")
    if not record2:
        raise HTTPException(status_code=404, detail=f"Record 2 ({payload.record_id_2}) not found")

    diff_str = DeviceBackupService.compare_backups(
        record1_content=record1.config_content or "",
        record2_content=record2.config_content or "",
        name1=f"Backup {record1.createdAt.strftime('%Y-%m-%d %H:%M:%S')}",
        name2=f"Backup {record2.createdAt.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    return BackupDiffResponse(diff_output=diff_str)
