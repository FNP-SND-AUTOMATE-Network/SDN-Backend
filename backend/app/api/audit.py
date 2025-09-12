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
from app.database import get_prisma_client

router = APIRouter(prefix="/audit", tags=["Audit Logs"])
security = HTTPBearer()

# Initialize services - จะ initialize ใน runtime
audit_service = None
user_service = None

def init_services():
    global audit_service, user_service
    prisma_client = get_prisma_client()
    if prisma_client:
        audit_service = AuditService(prisma_client)
        user_service = UserService(prisma_client)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """ตรวจสอบ JWT token และดึงข้อมูล user"""
    try:
        init_services()  # Initialize services with prisma client
        # ตรวจสอบ token
        user_id = await user_service.verify_access_token(credentials.credentials)
        
        # ดึงข้อมูล user
        user = await user_service.get_user_by_id(user_id)
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
    limit: int = Query(50, ge=1, le=1000, description="จำนวนรายการต่อหน้า"),
    offset: int = Query(0, ge=0, description="เริ่มจากรายการที่"),
    current_user: dict = Depends(get_current_user)
):
    """
    ดึงรายการ Audit Logs
    
    - **actor_user_id**: Filter ตาม user ที่ทำการกระทำ
    - **target_user_id**: Filter ตาม user ที่ถูกกระทำ
    - **action**: Filter ตามประเภทการกระทำ
    - **start_date**: วันที่เริ่มต้น (ISO format)
    - **end_date**: วันที่สิ้นสุด (ISO format)
    - **limit**: จำนวนรายการต่อหน้า (1-1000)
    - **offset**: เริ่มจากรายการที่
    """
    try:
        # สร้าง filter object
        filters = AuditLogFilter(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=action,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )

        # ดึงข้อมูล
        audit_logs, total = await audit_service.get_audit_logs(filters)

        # คำนวณ has_more
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
        raise HTTPException(status_code=500, detail="เกิดข้อผิดพลาดในการดึงข้อมูล Audit Logs")


@router.get("/logs/{audit_id}", response_model=AuditLogResponse)
async def get_audit_log(
    audit_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    ดึง Audit Log ตาม ID
    """
    try:
        audit_log = await audit_service.get_audit_log_by_id(audit_id)
        
        if not audit_log:
            raise HTTPException(status_code=404, detail="ไม่พบ Audit Log ที่ระบุ")
        
        return audit_log

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting audit log: {e}")
        raise HTTPException(status_code=500, detail="เกิดข้อผิดพลาดในการดึงข้อมูล Audit Log")


@router.post("/logs", response_model=AuditLogResponse)
async def create_audit_log(
    request: Request,
    audit_data: AuditLogCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    สร้าง Audit Log ใหม่ (สำหรับ admin เท่านั้น)
    """
    try:
        # ตรวจสอบสิทธิ์ admin (สมมติว่า role เป็น ADMIN)
        if current_user.get("role") != "ADMIN":
            raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์สร้าง Audit Log")

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
        audit_log = await audit_service.create_audit_log(audit_data)
        
        return audit_log

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating audit log: {e}")
        raise HTTPException(status_code=500, detail="เกิดข้อผิดพลาดในการสร้าง Audit Log")


@router.get("/stats")
async def get_audit_stats(
    start_date: Optional[datetime] = Query(None, description="วันที่เริ่มต้น"),
    end_date: Optional[datetime] = Query(None, description="วันที่สิ้นสุด"),
    current_user: dict = Depends(get_current_user)
):
    """
    ดึงสถิติ Audit Logs
    """
    try:
        # สร้าง where clause สำหรับ date filter
        where_clause = {}
        if start_date or end_date:
            date_filter = {}
            if start_date:
                date_filter["gte"] = start_date
            if end_date:
                date_filter["lte"] = end_date
            where_clause["createdAt"] = date_filter

        init_services()  # Initialize services with prisma client
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
            SELECT "actorUserId", COUNT(*) as count
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
            user_id = actor_data.get("actorUserId") or actor_data.get("actorUserId")
            if user_id:
                user = await user_service.get_user_by_id(user_id)
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
        raise HTTPException(status_code=500, detail="เกิดข้อผิดพลาดในการดึงสถิติ Audit Logs")
