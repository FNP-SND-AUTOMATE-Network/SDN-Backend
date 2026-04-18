from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import Dict, Any, Optional
from app.database import get_db
from app.api.users import get_current_user
from app.services.policy_service import PolicyService
from app.models.policy import (
    PolicyCreate,
    PolicyUpdate,
    PolicyResponse,
    PolicyListResponse,
    PolicyCreateResponse,
    PolicyUpdateResponse,
    PolicyDeleteResponse
)
from prisma import Prisma
from app.services.audit_service import AuditService
from app.models.audit import AuditAction
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/policies", tags=["Policies"])

def get_policy_service(db: Prisma = Depends(get_db)) -> PolicyService:
    return PolicyService(db)

def get_audit_service(db = Depends(get_db)):
    return AuditService(db)

@router.get("/", response_model=PolicyListResponse)
async def get_policies(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    search: Optional[str] = Query(None, description="Search by policy_name, description"),
    parent_policy_id: Optional[str] = Query(None, description="Filter by parent policy ID"),
    include_usage: bool = Query(False, description="Include usage count"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    policy_svc: PolicyService = Depends(get_policy_service)
):
    try:
        policies, total = await policy_svc.get_policies(
            page=page,
            page_size=page_size,
            search=search,
            parent_policy_id=parent_policy_id,
            include_usage=include_usage
        )

        return PolicyListResponse(
            total=total,
            page=page,
            page_size=page_size,
            policies=policies
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting policies: {str(e)}"
        )

@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: str,
    include_usage: bool = Query(False, description="Include usage count"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    policy_svc: PolicyService = Depends(get_policy_service)
):
    try:
        policy = await policy_svc.get_policy_by_id(policy_id, include_usage=include_usage)
        
        if not policy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Policy not found"
            )
        
        return policy

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting policy: {str(e)}"
        )

@router.post("/", response_model=PolicyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    request: Request,
    policy_data: PolicyCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    policy_svc: PolicyService = Depends(get_policy_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to create a policy"
            )

        policy = await policy_svc.create_policy(policy_data, current_user["id"])
        
        if not policy:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create policy"
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_generic_system_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.POLICY_CREATE,
                entity_type="POLICY",
                entity_id=policy.id,
                entity_name=policy.policy_name,
                changes=policy_data.dict(exclude_unset=True),
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return PolicyCreateResponse(
            message="Policy created successfully",
            policy=policy
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
            detail=f"Error creating policy: {str(e)}"
        )

@router.put("/{policy_id}", response_model=PolicyUpdateResponse)
async def update_policy(
    request: Request,
    policy_id: str,
    update_data: PolicyUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    policy_svc: PolicyService = Depends(get_policy_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update a policy"
            )

        policy = await policy_svc.update_policy(policy_id, update_data)
        
        if not policy:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update policy"
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_generic_system_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.POLICY_UPDATE,
                entity_type="POLICY",
                entity_id=policy.id,
                entity_name=policy.policy_name,
                changes=update_data.dict(exclude_unset=True),
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return PolicyUpdateResponse(
            message="Policy updated successfully",
            policy=policy
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
            detail=f"Error updating policy: {str(e)}"
        )

@router.delete("/{policy_id}", response_model=PolicyDeleteResponse)
async def delete_policy(
    request: Request,
    policy_id: str,
    force: bool = Query(False, description="Force delete even if in use"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    policy_svc: PolicyService = Depends(get_policy_service),
    audit_svc: AuditService = Depends(get_audit_service)
):
    try:
        if force:
            if current_user["role"] != "OWNER":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to delete a policy"
                )
        else:
            if current_user["role"] not in ["ADMIN", "OWNER"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to delete a policy"
                )

        old_policy = await policy_svc.get_policy_by_id(policy_id)
        if not old_policy:
            raise HTTPException(status_code=404, detail="Policy not found")

        success = await policy_svc.delete_policy(policy_id, force=force)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete policy"
            )

        try:
            client_ip = request.client.host if request.client else "unknown"
            if "x-forwarded-for" in request.headers:
                client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
            elif "x-real-ip" in request.headers:
                client_ip = request.headers["x-real-ip"]
                
            await audit_svc.create_generic_system_audit(
                actor_user_id=current_user["id"],
                action=AuditAction.POLICY_DELETE,
                entity_type="POLICY",
                entity_id=policy_id,
                entity_name=old_policy.policy_name,
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", "unknown")
            )
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

        return PolicyDeleteResponse(
            message="Policy deleted successfully"
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
            detail=f"Error deleting policy: {str(e)}"
        )

