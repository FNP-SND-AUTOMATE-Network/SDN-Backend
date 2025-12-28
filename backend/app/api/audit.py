from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, List
from datetime import datetime
import json

from app.models.audit import (
    AuditLogFilter, 
    AuditLogListResponse, 
    AuditLogResponse, 
    AuditAction,
    AuditLogCreate
)
from app.services.audit_service import AuditService
from app.services.user_service import UserService

# ใช้ global prisma client จาก database.py
from app.database import get_prisma_client, is_prisma_client_ready

router = APIRouter(prefix="/audit", tags=["Audit Logs"])
security = HTTPBearer()

# Initialize services - จะ initialize ใน runtime
audit_service = None
user_service = None

def get_services():
    global audit_service, user_service
    
    # Initialize services if not already done
    if audit_service is None or user_service is None:
        if not is_prisma_client_ready():
            raise HTTPException(
                status_code=500,
                detail="Database connection not ready. Please try again."
            )
        
        prisma_client = get_prisma_client()
        audit_service = AuditService(prisma_client)
        user_service = UserService(prisma_client)
    
    return audit_service, user_service


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    #ตรวจสอบ JWT token และดึงข้อมูล user
    try:
        # Get initialized services
        audit_svc, user_svc = get_services()
        
        #ตรวจสอบ token
        user_id = await user_svc.verify_access_token(credentials.credentials)
        
        # ดึงข้อมูล user
        user = await user_svc.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        return user
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.get("/logs", response_model=AuditLogListResponse)
async def get_audit_logs(
    request: Request,
    actor_user_id: Optional[str] = Query(None, description="Filter by actor user ID"),
    target_user_id: Optional[str] = Query(None, description="Filter by target user ID"),
    action: Optional[AuditAction] = Query(None, description="Filter by action"),
    start_date: Optional[datetime] = Query(None, description="Filter from date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="Filter to date (ISO format)"),
    limit: int = Query(50, ge=1, le=1000, description="Number of items per page"),
    offset: int = Query(0, ge=0, description="Start from item"),
    current_user: dict = Depends(get_current_user)
):
    try:
        # Get initialized services
        audit_svc, user_svc = get_services()
        
        #สร้าง filter object
        filters = AuditLogFilter(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=action,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )

        #ดึงข้อมูล
        audit_logs, total = await audit_svc.get_audit_logs(filters)

        #คำนวณ has_more
        has_more = (offset + limit) < total

        return AuditLogListResponse(
            items=audit_logs,
            total=total,
            limit=limit,
            offset=offset,
            has_more=has_more
        )

    except Exception as e:
        print(f"Error getting audit logs: {e}")
        raise HTTPException(status_code=500, detail="Error getting audit logs")


@router.get("/logs/{audit_id}", response_model=AuditLogResponse)
async def get_audit_log(
    audit_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        # Get initialized services
        audit_svc, user_svc = get_services()
        
        audit_log = await audit_svc.get_audit_log_by_id(audit_id)
        
        if not audit_log:
            raise HTTPException(status_code=404, detail="Audit Log not found")
        
        return audit_log

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting audit log: {e}")
        raise HTTPException(status_code=500, detail="Error getting audit log")


@router.post("/logs", response_model=AuditLogResponse)
async def create_audit_log(
    request: Request,
    audit_data: AuditLogCreate,
    current_user: dict = Depends(get_current_user)
):
    try:
        # Get initialized services
        audit_svc, user_svc = get_services()
        
        # ตรวจสอบสิทธิ์ admin (สมมติว่า role เป็น ADMIN)
        if current_user.get("role") != "ADMIN":
            raise HTTPException(status_code=403, detail="User does not have permission to create audit log")

        # เพิ่มข้อมูล IP และ User Agent ลงใน details
        if not audit_data.details:
            audit_data.details = {}
        
        # ดึง IP address
        client_ip = request.client.host
        if "x-forwarded-for" in request.headers:
            client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
        elif "x-real-ip" in request.headers:
            client_ip = request.headers["x-real-ip"]
        
        audit_data.details.update({
            "created_by": current_user["id"],
            "ip_address": client_ip,
            "user_agent": request.headers.get("user-agent"),
            "manual_entry": True,
            "timestamp": datetime.now().isoformat()
        })

        # สร้าง audit log
        audit_log = await audit_svc.create_audit_log(audit_data)
        
        return audit_log

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating audit log: {e}")
        raise HTTPException(status_code=500, detail="Error creating audit log")


@router.get("/stats")
async def get_audit_stats(
    start_date: Optional[datetime] = Query(None, description="Start date"),
    end_date: Optional[datetime] = Query(None, description="End date"),
    current_user: dict = Depends(get_current_user)
):
    try:
        #สร้าง where clause สำหรับ date filter
        where_clause = {}
        if start_date or end_date:
            date_filter = {}
            if start_date:
                date_filter["gte"] = start_date
            if end_date:
                date_filter["lte"] = end_date
            where_clause["createdAt"] = date_filter

        # Get initialized services
        audit_svc, user_svc = get_services()
        prisma_client = get_prisma_client()
        
        # นับจำนวนแต่ละ action
        actions_count = {}
        for action in AuditAction:
            count = await prisma_client.auditlog.count(
                where={**where_clause, "action": action.value}
            )
            actions_count[action.value] = count

        # นับจำนวนรวม
        total_count = await prisma_client.auditlog.count(where=where_clause)

        # ดึง top users (actors) - ใช้ query ธรรมดาแทน group_by เพราะ Prisma Python ไม่รองรับ
        top_actors_raw = await prisma_client.query_raw(
            """
            SELECT "actorUserId" as actor_user_id, COUNT(*) as count
            FROM "AuditLog"
            WHERE "actorUserId" IS NOT NULL
            GROUP BY "actorUserId"
            ORDER BY count DESC
            LIMIT 10
            """
        )

        # ดึงข้อมูล user สำหรับ top actors
        top_actors = []
        for actor_data in top_actors_raw:
            # Use the alias from SQL query
            user_id = actor_data.get("actor_user_id")
            if user_id:
                user = await user_svc.get_user_by_id(user_id)
                if user:
                    top_actors.append({
                        "user_id": user_id,
                        "user_email": user["email"],
                        "user_name": f"{user['name']} {user['surname']}",
                        "count": actor_data.get("count", 0)
                    })

        return {
            "total_logs": total_count,
            "actions_count": actions_count,
            "top_actors": top_actors,
            "date_range": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None
            }
        }

    except Exception as e:
        print(f"Error getting audit stats: {e}")
        raise HTTPException(status_code=500, detail="Error getting audit stats")
