from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.local_site import (
    LocalSiteCreate,
    LocalSiteUpdate,
    LocalSiteResponse
)

class LocalSiteService:
    """Service สำหรับจัดการ LocalSite"""

    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def create_local_site(self, site_data: LocalSiteCreate) -> Optional[LocalSiteResponse]:
        """สร้าง LocalSite ใหม่"""
        try:
            # ตรวจสอบว่า site_code ซ้ำหรือไม่
            existing_site = await self.prisma.localsite.find_unique(
                where={"site_code": site_data.site_code}
            )
            if existing_site:
                raise ValueError(f"รหัสสถานที่ {site_data.site_code} มีอยู่ในระบบแล้ว")

            # สร้าง LocalSite ใหม่
            site = await self.prisma.localsite.create(
                data={
                    "site_code": site_data.site_code,
                    "site_name": site_data.site_name,
                    "site_type": site_data.site_type.value,
                    "building_name": site_data.building_name,
                    "floor_number": site_data.floor_number,
                    "rack_number": site_data.rack_number,
                    "address": site_data.address,
                    "address_detail": site_data.address_detail,
                    "sub_district": site_data.sub_district,
                    "district": site_data.district,
                    "city": site_data.city,
                    "zip_code": site_data.zip_code,
                    "country": site_data.country
                }
            )

            return LocalSiteResponse(
                id=site.id,
                site_code=site.site_code,
                site_name=site.site_name,
                site_type=site.site_type,
                building_name=site.building_name,
                floor_number=site.floor_number,
                rack_number=site.rack_number,
                address=site.address,
                address_detail=site.address_detail,
                sub_district=site.sub_district,
                district=site.district,
                city=site.city,
                zip_code=site.zip_code,
                country=site.country,
                created_at=site.createdAt,
                updated_at=site.updatedAt,
                device_count=0
            )

        except Exception as e:
            print(f"Error creating local site: {e}")
            if "มีอยู่ในระบบแล้ว" in str(e):
                raise e
            return None

    async def get_local_sites(
        self,
        page: int = 1,
        page_size: int = 20,
        site_type: Optional[str] = None,
        search: Optional[str] = None
    ) -> tuple[List[LocalSiteResponse], int]:
        """ดึงรายการ LocalSite ทั้งหมด พร้อม pagination และ filter"""
        try:
            # สร้าง filter conditions
            where_conditions: Dict[str, Any] = {}
            
            if site_type:
                where_conditions["site_type"] = site_type
            
            if search:
                where_conditions["OR"] = [
                    {"site_code": {"contains": search, "mode": "insensitive"}},
                    {"site_name": {"contains": search, "mode": "insensitive"}},
                    {"address": {"contains": search, "mode": "insensitive"}},
                    {"city": {"contains": search, "mode": "insensitive"}}
                ]

            # นับจำนวนทั้งหมด
            total = await self.prisma.localsite.count(where=where_conditions)

            # ดึงข้อมูลตาม pagination
            skip = (page - 1) * page_size
            sites = await self.prisma.localsite.find_many(
                where=where_conditions,
                skip=skip,
                take=page_size,
                order={"createdAt": "desc"},
                include={
                    "deviceNetworks": True
                }
            )

            # แปลงเป็น response model
            site_responses = []
            for site in sites:
                site_responses.append(LocalSiteResponse(
                    id=site.id,
                    site_code=site.site_code,
                    site_name=site.site_name,
                    site_type=site.site_type,
                    building_name=site.building_name,
                    floor_number=site.floor_number,
                    rack_number=site.rack_number,
                    address=site.address,
                    address_detail=site.address_detail,
                    sub_district=site.sub_district,
                    district=site.district,
                    city=site.city,
                    zip_code=site.zip_code,
                    country=site.country,
                    created_at=site.createdAt,
                    updated_at=site.updatedAt,
                    device_count=len(site.deviceNetworks) if site.deviceNetworks else 0
                ))

            return site_responses, total

        except Exception as e:
            print(f"Error getting local sites: {e}")
            return [], 0

    async def get_local_site_by_id(self, site_id: str) -> Optional[LocalSiteResponse]:
        """ดึงข้อมูล LocalSite ตาม ID"""
        try:
            site = await self.prisma.localsite.find_unique(
                where={"id": site_id},
                include={
                    "deviceNetworks": True
                }
            )

            if not site:
                return None

            return LocalSiteResponse(
                id=site.id,
                site_code=site.site_code,
                site_name=site.site_name,
                site_type=site.site_type,
                building_name=site.building_name,
                floor_number=site.floor_number,
                rack_number=site.rack_number,
                address=site.address,
                address_detail=site.address_detail,
                sub_district=site.sub_district,
                district=site.district,
                city=site.city,
                zip_code=site.zip_code,
                country=site.country,
                created_at=site.createdAt,
                updated_at=site.updatedAt,
                device_count=len(site.deviceNetworks) if site.deviceNetworks else 0
            )

        except Exception as e:
            print(f"Error getting local site by id: {e}")
            return None

    async def update_local_site(
        self,
        site_id: str,
        update_data: LocalSiteUpdate
    ) -> Optional[LocalSiteResponse]:
        """อัปเดต LocalSite"""
        try:
            # ตรวจสอบว่า site มีอยู่หรือไม่
            existing_site = await self.prisma.localsite.find_unique(
                where={"id": site_id}
            )

            if not existing_site:
                raise ValueError("ไม่พบสถานที่ที่ต้องการอัปเดต")

            # เตรียมข้อมูลสำหรับอัปเดต
            update_dict: Dict[str, Any] = {}
            
            if update_data.site_code is not None:
                # ตรวจสอบว่า site_code ซ้ำหรือไม่
                if update_data.site_code != existing_site.site_code:
                    duplicate = await self.prisma.localsite.find_unique(
                        where={"site_code": update_data.site_code}
                    )
                    if duplicate:
                        raise ValueError(f"รหัสสถานที่ {update_data.site_code} มีอยู่ในระบบแล้ว")
                update_dict["site_code"] = update_data.site_code

            if update_data.site_name is not None:
                update_dict["site_name"] = update_data.site_name

            if update_data.site_type is not None:
                update_dict["site_type"] = update_data.site_type.value

            if update_data.building_name is not None:
                update_dict["building_name"] = update_data.building_name

            if update_data.floor_number is not None:
                update_dict["floor_number"] = update_data.floor_number

            if update_data.rack_number is not None:
                update_dict["rack_number"] = update_data.rack_number

            if update_data.address is not None:
                update_dict["address"] = update_data.address

            if update_data.address_detail is not None:
                update_dict["address_detail"] = update_data.address_detail

            if update_data.sub_district is not None:
                update_dict["sub_district"] = update_data.sub_district

            if update_data.district is not None:
                update_dict["district"] = update_data.district

            if update_data.city is not None:
                update_dict["city"] = update_data.city

            if update_data.zip_code is not None:
                update_dict["zip_code"] = update_data.zip_code

            if update_data.country is not None:
                update_dict["country"] = update_data.country

            # ตรวจสอบว่ามีข้อมูลที่จะอัปเดตหรือไม่
            if not update_dict:
                raise ValueError("ไม่มีข้อมูลที่จะอัปเดต")

            # อัปเดตข้อมูล
            updated_site = await self.prisma.localsite.update(
                where={"id": site_id},
                data=update_dict,
                include={
                    "deviceNetworks": True
                }
            )

            return LocalSiteResponse(
                id=updated_site.id,
                site_code=updated_site.site_code,
                site_name=updated_site.site_name,
                site_type=updated_site.site_type,
                building_name=updated_site.building_name,
                floor_number=updated_site.floor_number,
                rack_number=updated_site.rack_number,
                address=updated_site.address,
                address_detail=updated_site.address_detail,
                sub_district=updated_site.sub_district,
                district=updated_site.district,
                city=updated_site.city,
                zip_code=updated_site.zip_code,
                country=updated_site.country,
                created_at=updated_site.createdAt,
                updated_at=updated_site.updatedAt,
                device_count=len(updated_site.deviceNetworks) if updated_site.deviceNetworks else 0
            )

        except Exception as e:
            print(f"Error updating local site: {e}")
            if "ไม่พบสถานที่" in str(e) or "มีอยู่ในระบบแล้ว" in str(e) or "ไม่มีข้อมูลที่จะอัปเดต" in str(e):
                raise e
            return None

    async def delete_local_site(self, site_id: str) -> bool:
        """ลบ LocalSite"""
        try:
            # ตรวจสอบว่า site มีอยู่หรือไม่
            existing_site = await self.prisma.localsite.find_unique(
                where={"id": site_id},
                include={
                    "deviceNetworks": True
                }
            )

            if not existing_site:
                raise ValueError("ไม่พบสถานที่ที่ต้องการลบ")

            # ตรวจสอบว่ามีอุปกรณ์ที่เชื่อมโยงหรือไม่
            if existing_site.deviceNetworks and len(existing_site.deviceNetworks) > 0:
                raise ValueError(f"ไม่สามารถลบสถานที่นี้ได้ เนื่องจากมีอุปกรณ์ {len(existing_site.deviceNetworks)} รายการที่เชื่อมโยงอยู่")

            # ลบ site
            await self.prisma.localsite.delete(
                where={"id": site_id}
            )

            return True

        except Exception as e:
            print(f"Error deleting local site: {e}")
            if "ไม่พบสถานที่" in str(e) or "ไม่สามารถลบสถานที่นี้ได้" in str(e):
                raise e
            return False

