from typing import Optional, List
import os
import hashlib
from pathlib import Path
from app.models.os_file import (
    OSFileResponse,
    RelatedUserInfoFile,
    RelatedOSInfoFile
)

class OSFileService:
    #Service สำหรับจัดการ OS File uploads

    def __init__(self, prisma_client):
        self.prisma = prisma_client
        #กำหนด upload directory
        self.upload_dir = Path("/app/uploads/os_files")
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def _calculate_checksum(self, file_content: bytes) -> str:
        #คำนวณ SHA256 checksum ของไฟล์
        return hashlib.sha256(file_content).hexdigest()

    async def save_file(
        self,
        os_id: str,
        file_content: bytes,
        file_name: str,
        file_type: Optional[str],
        version: Optional[str],
        user_id: str
    ) -> Optional[OSFileResponse]:
        #บันทึกไฟล์และสร้าง record ในฐานข้อมูล
        try:
            #ตรวจสอบว่า OS มีอยู่จริง
            os = await self.prisma.operatingsystem.find_unique(where={"id": os_id})
            if not os:
                raise ValueError(f"ไม่พบ Operating System ID: {os_id}")

            #คำนวณ checksum
            checksum = self._calculate_checksum(file_content)
            file_size = len(file_content)

            #สร้างชื่อไฟล์ที่ไม่ซ้ำ (ใช้ checksum prefix)
            safe_filename = f"{checksum[:8]}_{file_name}"
            file_path = self.upload_dir / safe_filename

            #บันทึกไฟล์
            with open(file_path, "wb") as f:
                f.write(file_content)

            #บันทึก record ในฐานข้อมูล
            os_file = await self.prisma.osfile.create(
                data={
                    "os_id": os_id,
                    "file_name": file_name,
                    "file_path": str(file_path),
                    "file_size": file_size,
                    "file_type": file_type,
                    "version": version,
                    "checksum": checksum,
                    "uploaded_by": user_id
                },
                include={
                    "uploadedByUser": True,
                    "operatingSystem": True
                }
            )

            return self._build_file_response(os_file)

        except Exception as e:
            print(f"Error saving file: {e}")
            #ลบไฟล์ถ้าบันทึก record ไม่สำเร็จ
            if 'file_path' in locals() and file_path.exists():
                file_path.unlink()
            
            if "ไม่พบ Operating System" in str(e):
                raise e
            return None

    def _build_file_response(self, os_file) -> OSFileResponse:
        #สร้าง OSFileResponse จาก Prisma object
        
        uploaded_by_user = None
        if os_file.uploadedByUser:
            uploaded_by_user = RelatedUserInfoFile(
                id=os_file.uploadedByUser.id,
                email=os_file.uploadedByUser.email,
                name=os_file.uploadedByUser.name,
                surname=os_file.uploadedByUser.surname
            )

        operating_system = None
        if os_file.operatingSystem:
            operating_system = RelatedOSInfoFile(
                id=os_file.operatingSystem.id,
                os_type=os_file.operatingSystem.os_type
            )

        return OSFileResponse(
            id=os_file.id,
            os_id=os_file.os_id,
            file_name=os_file.file_name,
            file_path=os_file.file_path,
            file_size=os_file.file_size,
            file_type=os_file.file_type,
            version=os_file.version,
            checksum=os_file.checksum,
            uploaded_by=os_file.uploaded_by,
            created_at=os_file.createdAt,
            updated_at=os_file.updatedAt,
            uploaded_by_user=uploaded_by_user,
            operating_system=operating_system
        )

    async def get_files_by_os(self, os_id: str) -> List[OSFileResponse]:
        #ดึงรายการไฟล์ทั้งหมดของ OS
        try:
            files = await self.prisma.osfile.find_many(
                where={"os_id": os_id},
                order={"createdAt": "desc"},
                include={
                    "uploadedByUser": True,
                    "operatingSystem": True
                }
            )

            return [self._build_file_response(f) for f in files]

        except Exception as e:
            print(f"Error getting files: {e}")
            return []

    async def get_file_by_id(self, file_id: str) -> Optional[OSFileResponse]:
        #ดึงข้อมูลไฟล์ตาม ID
        try:
            os_file = await self.prisma.osfile.find_unique(
                where={"id": file_id},
                include={
                    "uploadedByUser": True,
                    "operatingSystem": True
                }
            )

            if not os_file:
                return None

            return self._build_file_response(os_file)

        except Exception as e:
            print(f"Error getting file by id: {e}")
            return None

    async def delete_file(self, file_id: str) -> bool:
        #ลบไฟล์และ record
        try:
            os_file = await self.prisma.osfile.find_unique(where={"id": file_id})

            if not os_file:
                raise ValueError("ไม่พบไฟล์ที่ต้องการลบ")

            #ลบไฟล์จาก filesystem
            file_path = Path(os_file.file_path)
            if file_path.exists():
                file_path.unlink()

            #ลบ record จากฐานข้อมูล
            await self.prisma.osfile.delete(where={"id": file_id})

            return True

        except Exception as e:
            print(f"Error deleting file: {e}")
            if "ไม่พบไฟล์" in str(e):
                raise e
            return False

    def get_file_path(self, file_id: str, file_path: str) -> Optional[Path]:
        #ดึง path ของไฟล์สำหรับดาวน์โหลด
        try:
            path = Path(file_path)
            if path.exists():
                return path
            return None
        except Exception as e:
            print(f"Error getting file path: {e}")
            return None

