from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from pydantic import BaseModel
from typing import List, Dict, Any

from app.database import get_db
from app.api.users import get_current_user
from app.services.intent_engine_service import IntentEngineService
from app.services.audit_service import AuditService
from app.models.audit import AuditAction
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deployments", tags=["Deployments"])

def get_audit_service(db = Depends(get_db)):
    return AuditService(db)

class DeploymentRequest(BaseModel):
    template_id: str
    device_ids: List[str]
    variables: Dict[str, Any]

@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def create_deployment(
    req: DeploymentRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
    audit_svc: AuditService = Depends(get_audit_service)
):
    """
    Triggers an asynchronous configuration deployment to multiple devices based on a Jinja2 template.
    Returns 202 Accepted immediately.
    """
    svc = IntentEngineService(db)
    user_id = current_user.get("id")
    
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated properly")
        
    try:
        job_id = await svc.trigger_deployment(
            template_id=req.template_id, 
            device_ids=req.device_ids, 
            variables=req.variables, 
            user_id=user_id, 
            background_tasks=background_tasks
        )
        
        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_generic_system_audit(
                actor_user_id=user_id,
                action=AuditAction.DEPLOYMENT_START,
                entity_type="DEPLOYMENT",
                entity_id=job_id,
                entity_name=f"Template {req.template_id} to {len(req.device_ids)} devices",
                changes={"template_id": req.template_id, "device_ids": req.device_ids, "variables": req.variables},
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")
        
        return {
            "message": "Deployment job started successfully.",
            "deployment_id": job_id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{job_id}")
async def get_deployment_status(
    job_id: str, 
    db = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    """
    Fetch the status of a bulk deployment job and its associated device records.
    """
    job = await db.deploymentjob.find_unique(
        where={"id": job_id},
        include={"records": {"include": {"device": True}}, "template": True}
    )
    if not job:
        raise HTTPException(status_code=404, detail="Deployment job not found")
        
    return {
        "id": job.id,
        "status": job.status,
        "template_name": job.template.template_name if job.template else "Unknown",
        "total_devices": job.total_devices,
        "success_devices": job.success_devices,
        "failed_devices": job.failed_devices,
        "error_message": job.error_message,
        "created_at": job.createdAt,
        "records": [
            {
                "id": rec.id,
                "device_name": rec.device.device_name if rec.device else "Unknown",
                "device_ip": rec.device.netconf_host if rec.device else "Unknown",
                "status": rec.status,
                "error_message": rec.error_message,
                "rendered_config": rec.rendered_config
            }
            for rec in job.records
        ] if job.records else []
    }
