from typing import Optional, List, Dict, Any
from app.models.interface import (
    InterfaceCreate,
    InterfaceUpdate,
    InterfaceResponse,
    RelatedDeviceInfo
)

class InterfaceService:
    """Service สำหรับจัดการ Interface"""

    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def create_interface(self, interface_data: InterfaceCreate) -> Optional[InterfaceResponse]:
        """สร้าง Interface ใหม่"""
        try:
            # ตรวจสอบว่า device มีอยู่จริง
            device = await self.prisma.devicenetwork.find_unique(
                where={"id": interface_data.device_id}
            )
            if not device:
                raise ValueError(f"ไม่พบ Device ID: {interface_data.device_id}")

            # ตรวจสอบว่า interface name ซ้ำใน device เดียวกันหรือไม่
            existing_interface = await self.prisma.interface.find_first(
                where={
                    "device_id": interface_data.device_id,
                    "name": interface_data.name
                }
            )
            if existing_interface:
                raise ValueError(f"Interface '{interface_data.name}' มีอยู่ใน Device นี้แล้ว")

            # สร้าง Interface
            interface = await self.prisma.interface.create(
                data={
                    "name": interface_data.name,
                    "device_id": interface_data.device_id,
                    "label": interface_data.label,
                    "status": interface_data.status.value,
                    "type": interface_data.type.value,
                    "description": interface_data.description
                },
                include={"device": True}
            )

            return self._build_interface_response(interface)

        except Exception as e:
            print(f"Error creating interface: {e}")
            if "ไม่พบ Device" in str(e) or "มีอยู่" in str(e):
                raise e
            return None

    def _build_interface_response(self, interface) -> InterfaceResponse:
        """สร้าง InterfaceResponse จาก Prisma object"""
        
        device_info = None
        if interface.device:
            device_info = RelatedDeviceInfo(
                id=interface.device.id,
                device_name=interface.device.device_name,
                device_model=interface.device.device_model,
                serial_number=interface.device.serial_number,
                type=interface.device.type
            )

        return InterfaceResponse(
            id=interface.id,
            name=interface.name,
            device_id=interface.device_id,
            label=interface.label,
            status=interface.status,
            type=interface.type,
            description=interface.description,
            created_at=interface.createdAt,
            updated_at=interface.updatedAt,
            device=device_info
        )

    async def get_interfaces(
        self,
        page: int = 1,
        page_size: int = 20,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        interface_type: Optional[str] = None,
        search: Optional[str] = None
    ) -> tuple[List[InterfaceResponse], int]:
        """ดึงรายการ Interface ทั้งหมด"""
        try:
            where_conditions: Dict[str, Any] = {}
            
            if device_id:
                where_conditions["device_id"] = device_id
            
            if status:
                where_conditions["status"] = status
            
            if interface_type:
                where_conditions["type"] = interface_type
            
            if search:
                where_conditions["OR"] = [
                    {"name": {"contains": search, "mode": "insensitive"}},
                    {"label": {"contains": search, "mode": "insensitive"}},
                    {"description": {"contains": search, "mode": "insensitive"}}
                ]

            total = await self.prisma.interface.count(where=where_conditions)
            skip = (page - 1) * page_size

            interfaces = await self.prisma.interface.find_many(
                where=where_conditions,
                skip=skip,
                take=page_size,
                order={"createdAt": "desc"},
                include={"device": True}
            )

            interface_responses = [self._build_interface_response(interface) for interface in interfaces]
            return interface_responses, total

        except Exception as e:
            print(f"Error getting interfaces: {e}")
            return [], 0

    async def get_interface_by_id(self, interface_id: str) -> Optional[InterfaceResponse]:
        """ดึงข้อมูล Interface ตาม ID"""
        try:
            interface = await self.prisma.interface.find_unique(
                where={"id": interface_id},
                include={"device": True}
            )

            if not interface:
                return None

            return self._build_interface_response(interface)

        except Exception as e:
            print(f"Error getting interface by id: {e}")
            return None

    async def update_interface(self, interface_id: str, update_data: InterfaceUpdate) -> Optional[InterfaceResponse]:
        """อัปเดต Interface"""
        try:
            existing_interface = await self.prisma.interface.find_unique(
                where={"id": interface_id}
            )

            if not existing_interface:
                raise ValueError("ไม่พบ Interface ที่ต้องการอัปเดต")

            update_dict: Dict[str, Any] = {}
            
            if update_data.name is not None:
                # ตรวจสอบว่า name ซ้ำใน device เดียวกันหรือไม่
                if update_data.name != existing_interface.name:
                    duplicate = await self.prisma.interface.find_first(
                        where={
                            "device_id": existing_interface.device_id,
                            "name": update_data.name
                        }
                    )
                    if duplicate:
                        raise ValueError(f"Interface '{update_data.name}' มีอยู่ใน Device นี้แล้ว")
                update_dict["name"] = update_data.name

            if update_data.label is not None:
                update_dict["label"] = update_data.label

            if update_data.status is not None:
                update_dict["status"] = update_data.status.value

            if update_data.type is not None:
                update_dict["type"] = update_data.type.value

            if update_data.description is not None:
                update_dict["description"] = update_data.description

            if not update_dict:
                raise ValueError("ไม่มีข้อมูลที่จะอัปเดต")

            updated_interface = await self.prisma.interface.update(
                where={"id": interface_id},
                data=update_dict,
                include={"device": True}
            )

            return self._build_interface_response(updated_interface)

        except Exception as e:
            print(f"Error updating interface: {e}")
            if "ไม่พบ Interface" in str(e) or "มีอยู่" in str(e) or "ไม่มีข้อมูลที่จะอัปเดต" in str(e):
                raise e
            return None

    async def delete_interface(self, interface_id: str) -> bool:
        """ลบ Interface"""
        try:
            existing_interface = await self.prisma.interface.find_unique(
                where={"id": interface_id}
            )

            if not existing_interface:
                raise ValueError("ไม่พบ Interface ที่ต้องการลบ")

            await self.prisma.interface.delete(where={"id": interface_id})
            return True

        except Exception as e:
            print(f"Error deleting interface: {e}")
            if "ไม่พบ Interface" in str(e):
                raise e
            return False

    async def get_interfaces_by_device(self, device_id: str) -> List[InterfaceResponse]:
        """ดึงรายการ Interface ทั้งหมดของ Device"""
        try:
            # ตรวจสอบว่า device มีอยู่จริง
            device = await self.prisma.devicenetwork.find_unique(
                where={"id": device_id}
            )
            if not device:
                raise ValueError(f"ไม่พบ Device ID: {device_id}")

            interfaces = await self.prisma.interface.find_many(
                where={"device_id": device_id},
                order={"name": "asc"},
                include={"device": True}
            )

            return [self._build_interface_response(interface) for interface in interfaces]

        except Exception as e:
            print(f"Error getting interfaces by device: {e}")
            if "ไม่พบ Device" in str(e):
                raise e
            return []

