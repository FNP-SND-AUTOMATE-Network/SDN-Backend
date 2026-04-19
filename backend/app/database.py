"""
Database Configuration
จัดการ Global Prisma Client Instance สำหรับเชื่อมต่อฐานข้อมูล

หน้าที่หลัก:
- เก็บ Prisma Client เป็น Singleton (ตัวแปร Global)
- ให้ทุก Service/API เข้าถึง Database ผ่าน get_prisma_client()
- ใช้เป็น FastAPI Dependency Injection ผ่าน get_db()
"""

from fastapi import HTTPException

# Global Prisma client instance
prisma_client = None


def get_prisma_client():
    """
    ดึง Prisma Client Instance สำหรับใช้งาน Database
    - ถ้ายังไม่ได้เชื่อมต่อ (client เป็น None) จะ raise HTTP 500
    - ใช้ในทุก Service ที่ต้องการเข้าถึงฐานข้อมูล
    """
    global prisma_client
    if prisma_client is None:
        raise HTTPException(
            status_code=500, 
            detail="Database connection not available. Server is starting up."
        )
    return prisma_client


def set_prisma_client(client):
    """
    ตั้งค่า Prisma Client Instance (เรียกจาก Lifespan Startup เท่านั้น)
    - รับ Prisma Client ที่ connect แล้วมาเก็บเป็น Global Variable
    """
    global prisma_client
    prisma_client = client


def is_prisma_client_ready():
    """
    ตรวจสอบว่า Prisma Client พร้อมใช้งานหรือยัง
    - คืนค่า True ถ้า client ถูก set แล้ว (Server เริ่มต้นเสร็จแล้ว)
    """
    global prisma_client
    return prisma_client is not None


def get_db():
    """
    FastAPI Dependency สำหรับ Inject Database Client เข้า API Route
    - ใช้ใน Depends(get_db) เพื่อให้ Route Handler เข้าถึง Prisma Client
    """
    return get_prisma_client()
