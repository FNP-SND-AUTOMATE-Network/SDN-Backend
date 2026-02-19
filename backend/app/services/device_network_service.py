from typing import Optional, List, Dict, Any
from app.models.device_network import (
    DeviceNetworkCreate,
    DeviceNetworkUpdate,
    DeviceNetworkResponse,
    RelatedTagInfo,
    RelatedOSInfo,
    RelatedSiteInfo,
    RelatedPolicyInfo,
    RelatedBackupInfo,
    RelatedTemplateInfo
)

class DeviceNetworkService:
    #Service สำหรับจัดการ Device Network

    def __init__(self, prisma_client):
        self.prisma = prisma_client

    async def _validate_foreign_keys(self, data: Dict[str, Any]) -> None:
        #ตรวจสอบ foreign keys ว่ามีอยู่จริงในระบบ
        
        if data.get('os_id'):
            os = await self.prisma.operatingsystem.find_unique(where={"id": data['os_id']})
            if not os:
                raise ValueError(f"ไม่พบ Operating System ID: {data['os_id']}")
        
        if data.get('local_site_id'):
            site = await self.prisma.localsite.find_unique(where={"id": data['local_site_id']})
            if not site:
                raise ValueError(f"ไม่พบ Local Site ID: {data['local_site_id']}")
        
        if data.get('policy_id'):
            policy = await self.prisma.policy.find_unique(where={"id": data['policy_id']})
            if not policy:
                raise ValueError(f"ไม่พบ Policy ID: {data['policy_id']}")
        
        if data.get('backup_id'):
            backup = await self.prisma.backup.find_unique(where={"id": data['backup_id']})
            if not backup:
                raise ValueError(f"ไม่พบ Backup ID: {data['backup_id']}")
        
        if data.get('configuration_template_id'):
            template = await self.prisma.configurationtemplate.find_unique(where={"id": data['configuration_template_id']})
            if not template:
                raise ValueError(f"ไม่พบ Configuration Template ID: {data['configuration_template_id']}")

    async def create_device(self, device_data: DeviceNetworkCreate) -> Optional[DeviceNetworkResponse]:
        #สร้าง Device Network ใหม่
        try:
            #ตรวจสอบว่า serial_number ซ้ำหรือไม่
            existing_device = await self.prisma.devicenetwork.find_unique(
                where={"serial_number": device_data.serial_number}
            )
            if existing_device:
                raise ValueError(f"Serial Number '{device_data.serial_number}' มีอยู่ในระบบแล้ว")

            #ตรวจสอบว่า mac_address ซ้ำหรือไม่
            existing_mac = await self.prisma.devicenetwork.find_unique(
                where={"mac_address": device_data.mac_address}
            )
            if existing_mac:
                raise ValueError(f"MAC Address '{device_data.mac_address}' มีอยู่ในระบบแล้ว")

            #ตรวจสอบ foreign keys
            await self._validate_foreign_keys({
                'os_id': device_data.os_id,
                'local_site_id': device_data.local_site_id,
                'policy_id': device_data.policy_id,
                'backup_id': device_data.backup_id,
                'configuration_template_id': device_data.configuration_template_id
            })

            # ตรวจสอบว่า node_id ซ้ำหรือไม่
            if device_data.node_id:
                existing_node = await self.prisma.devicenetwork.find_unique(
                    where={"node_id": device_data.node_id}
                )
                if existing_node:
                    raise ValueError(f"node_id '{device_data.node_id}' มีอยู่ในระบบแล้ว")

            #สร้าง Device — only include required fields, add optional fields conditionally
            create_data = {
                    "serial_number": device_data.serial_number,
                    "device_name": device_data.device_name,
                    "device_model": device_data.device_model,
                    "type": device_data.type.value,
                    "status": device_data.status.value,
                    "mac_address": device_data.mac_address,
            }

            # Optional fields — only include if they have values
            if device_data.ip_address:
                create_data["ip_address"] = device_data.ip_address
            if device_data.description:
                create_data["description"] = device_data.description
            if device_data.policy_id:
                create_data["policy_id"] = device_data.policy_id
            # Optional fields — only include if they have values
            # Prepare manual dictionary for Prisma create to avoid Pydantic serialization issues
            create_data_dict = {
                "serial_number": device_data.serial_number,
                "device_name": device_data.device_name,
                "device_model": device_data.device_model,
                "type": device_data.type.value if hasattr(device_data.type, 'value') else device_data.type,
                "status": device_data.status.value if hasattr(device_data.status, 'value') else device_data.status,
                "ip_address": device_data.ip_address,
                "mac_address": device_data.mac_address,
                "description": device_data.description,
                "phpipam_address_id": device_data.phpipam_address_id,
                "policy_id": device_data.policy_id,
                "os_id": device_data.os_id,
                "backup_id": device_data.backup_id,
                "local_site_id": device_data.local_site_id,
                "configuration_template_id": device_data.configuration_template_id,
                
                # NBI fields
                "node_id": device_data.node_id,
                "vendor": device_data.vendor.value if hasattr(device_data.vendor, 'value') else device_data.vendor,
                
                # NETCONF fields (from input or defaults)
                "netconf_host": device_data.netconf_host or device_data.ip_address,
                "netconf_port": device_data.netconf_port,
                "netconf_username": device_data.netconf_username,
                "netconf_password": device_data.netconf_password,
                
                "odl_mounted": False,
                "odl_connection_status": "UNABLE_TO_CONNECT"
            }

            # Filter out None values to prevent "Could not find field" errors if engine is strict or schema mismatch
            # This ensures we only send fields that actually have values
            final_create_data = {k: v for k, v in create_data_dict.items() if v is not None}
            
            # DEBUG: Print create payload
            print(f"DEBUG CREATE DEVICE PAYLOAD (FILTERED): {final_create_data}")
            
            device = await self.prisma.devicenetwork.create(
                data=final_create_data,
                include={
                    "tags": True,
                    "operatingSystem": True,
                    "localSite": True,
                    "configuration_template": True
                }
            )

            return self._build_device_response(device)

        except Exception as e:
            print(f"Error creating device: {e}")
            raise e

    def _build_device_response(self, device) -> DeviceNetworkResponse:
        #สร้าง DeviceNetworkResponse จาก Prisma object
        
        #Tags info (many-to-many)
        tags_info = []
        if hasattr(device, 'tags') and device.tags:
            for tag in device.tags:
                tags_info.append(RelatedTagInfo(
                    tag_id=tag.tag_id,
                    tag_name=tag.tag_name,
                    color=tag.color,
                    type=tag.type
                ))

        #OS info
        os_info = None
        if hasattr(device, 'operatingSystem') and device.operatingSystem:
            os_info = RelatedOSInfo(
                id=device.operatingSystem.id,
                os_type=device.operatingSystem.os_type
            )

        #Site info
        site_info = None
        if hasattr(device, 'localSite') and device.localSite:
            site_info = RelatedSiteInfo(
                id=device.localSite.id,
                site_code=device.localSite.site_code,
                site_name=device.localSite.site_name
            )

        #Policy info
        policy_info = None
        if hasattr(device, 'policy') and device.policy:
            policy_info = RelatedPolicyInfo(
                id=device.policy.id,
                policy_name=device.policy.policy_name
            )

        #Backup info
        backup_info = None
        if hasattr(device, 'backup') and device.backup:
            backup_info = RelatedBackupInfo(
                id=device.backup.id,
                backup_name=device.backup.backup_name,
                status=device.backup.status
            )

        #Template info
        template_info = None
        if hasattr(device, 'configuration_template') and device.configuration_template:
            template_info = RelatedTemplateInfo(
                id=device.configuration_template.id,
                template_name=device.configuration_template.template_name,
                template_type=device.configuration_template.template_type
            )

        # Determine ready_for_intent status
        ready_for_intent = (
            getattr(device, 'odl_mounted', False) and 
            getattr(device, 'odl_connection_status', 'UNABLE_TO_CONNECT') == 'CONNECTED' and
            getattr(device, 'node_id', None) is not None
        )

        return DeviceNetworkResponse(
            id=device.id,
            serial_number=device.serial_number,
            device_name=device.device_name,
            device_model=device.device_model,
            type=device.type,
            status=device.status,
            ip_address=getattr(device, 'ip_address', None),
            mac_address=device.mac_address,
            description=getattr(device, 'description', None),
            policy_id=getattr(device, 'policy_id', None),
            os_id=getattr(device, 'os_id', None),
            backup_id=getattr(device, 'backup_id', None),
            local_site_id=getattr(device, 'local_site_id', None),
            configuration_template_id=getattr(device, 'configuration_template_id', None),
            # NBI/ODL Fields
            node_id=getattr(device, 'node_id', None),
            vendor=getattr(device, 'vendor', 'OTHER'),
            netconf_host=getattr(device, 'netconf_host', None),
            netconf_port=getattr(device, 'netconf_port', 830) or 830,
            netconf_username=getattr(device, 'netconf_username', None),
            netconf_password=None,  # ไม่ส่ง password กลับไป frontend
            # ODL Status Fields
            odl_mounted=is_mounted,
            odl_connection_status=connection_status,
            last_synced_at=getattr(device, 'last_synced_at', None),
            ready_for_intent=ready_for_intent,
            # NETCONF Connection Fields
            netconf_host=getattr(device, 'netconf_host', None),
            netconf_port=getattr(device, 'netconf_port', 830),
            netconf_username=getattr(device, 'netconf_username', None),
            netconf_password=None,  # Don't return password for security
            # Timestamps and Relations
            created_at=device.createdAt,
            updated_at=device.updatedAt,
            tags=tags_info,
            operatingSystem=os_info,
            localSite=site_info,
            policy=policy_info,
            backup=backup_info,
            configuration_template=template_info
        )

    async def get_devices(
        self,
        page: int = 1,
        page_size: int = 20,
        device_type: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        os_id: Optional[str] = None,
        local_site_id: Optional[str] = None,
        policy_id: Optional[str] = None
    ) -> tuple[List[DeviceNetworkResponse], int]:
        #ดึงรายการ Device Network ทั้งหมด
        try:
            where_conditions: Dict[str, Any] = {}
            
            if device_type:
                where_conditions["type"] = device_type
            
            if status:
                where_conditions["status"] = status
            
            if os_id:
                where_conditions["os_id"] = os_id
            
            if local_site_id:
                where_conditions["local_site_id"] = local_site_id
            
            if policy_id:
                where_conditions["policy_id"] = policy_id
            
            if search:
                where_conditions["OR"] = [
                    {"device_name": {"contains": search, "mode": "insensitive"}},
                    {"device_model": {"contains": search, "mode": "insensitive"}},
                    {"serial_number": {"contains": search, "mode": "insensitive"}},
                    {"ip_address": {"contains": search, "mode": "insensitive"}},
                    {"description": {"contains": search, "mode": "insensitive"}}
                ]

            total = await self.prisma.devicenetwork.count(where=where_conditions)
            skip = (page - 1) * page_size

            devices = await self.prisma.devicenetwork.find_many(
                where=where_conditions,
                skip=skip,
                take=page_size,
                order={"createdAt": "desc"},
                include={
                    "tags": True,
                    "operatingSystem": True,
                    "localSite": True,
                    "configuration_template": True
                }
            )

            device_responses = [self._build_device_response(device) for device in devices]
            return device_responses, total

        except Exception as e:
            print(f"Error getting devices: {e}")
            return [], 0

    async def get_device_by_id(self, device_id: str) -> Optional[DeviceNetworkResponse]:
        #ดึงข้อมูล Device Network ตาม ID
        try:
            device = await self.prisma.devicenetwork.find_unique(
                where={"id": device_id},
                include={
                    "tags": True,
                    "operatingSystem": True,
                    "localSite": True,
                    "configuration_template": True
                }
            )

            if not device:
                return None

            return self._build_device_response(device)

        except Exception as e:
            print(f"Error getting device by id: {e}")
            return None

    async def update_device(self, device_id: str, update_data: DeviceNetworkUpdate) -> Optional[DeviceNetworkResponse]:
        #อัปเดต Device Network
        try:
            existing_device = await self.prisma.devicenetwork.find_unique(where={"id": device_id})

            if not existing_device:
                raise ValueError("ไม่พบ Device Network ที่ต้องการอัปเดต")

            update_dict: Dict[str, Any] = {}
            
            if update_data.serial_number is not None:
                if update_data.serial_number != existing_device.serial_number:
                    duplicate = await self.prisma.devicenetwork.find_unique(
                        where={"serial_number": update_data.serial_number}
                    )
                    if duplicate:
                        raise ValueError(f"Serial Number '{update_data.serial_number}' มีอยู่ในระบบแล้ว")
                update_dict["serial_number"] = update_data.serial_number

            if update_data.mac_address is not None:
                if update_data.mac_address != existing_device.mac_address:
                    duplicate = await self.prisma.devicenetwork.find_unique(
                        where={"mac_address": update_data.mac_address}
                    )
                    if duplicate:
                        raise ValueError(f"MAC Address '{update_data.mac_address}' มีอยู่ในระบบแล้ว")
                update_dict["mac_address"] = update_data.mac_address

            if update_data.device_name is not None:
                update_dict["device_name"] = update_data.device_name

            if update_data.device_model is not None:
                update_dict["device_model"] = update_data.device_model

            if update_data.type is not None:
                update_dict["type"] = update_data.type.value

            if update_data.status is not None:
                update_dict["status"] = update_data.status.value

            if update_data.ip_address is not None:
                update_dict["ip_address"] = update_data.ip_address

            if update_data.description is not None:
                update_dict["description"] = update_data.description

            # Foreign keys - ตรวจสอบก่อนอัปเดต
            foreign_keys_to_validate = {}
            
            # Uncommented fields (requires 'prisma generate')
            if update_data.os_id is not None:
                foreign_keys_to_validate['os_id'] = update_data.os_id
                update_dict["os_id"] = update_data.os_id

            if update_data.local_site_id is not None:
                foreign_keys_to_validate['local_site_id'] = update_data.local_site_id
                update_dict["local_site_id"] = update_data.local_site_id

            if update_data.policy_id is not None:
                foreign_keys_to_validate['policy_id'] = update_data.policy_id
                update_dict["policy_id"] = update_data.policy_id

            if update_data.backup_id is not None:
                foreign_keys_to_validate['backup_id'] = update_data.backup_id
                update_dict["backup_id"] = update_data.backup_id

            if update_data.configuration_template_id is not None:
                foreign_keys_to_validate['configuration_template_id'] = update_data.configuration_template_id
                update_dict["configuration_template_id"] = update_data.configuration_template_id

            # NBI/ODL Fields
            if update_data.node_id is not None:
                # ตรวจสอบว่า node_id ไม่ซ้ำกับ device อื่น
                if update_data.node_id != existing_device.node_id:
                    duplicate = await self.prisma.devicenetwork.find_unique(
                        where={"node_id": update_data.node_id}
                    )
                    if duplicate:
                        raise ValueError(f"node_id '{update_data.node_id}' มีอยู่ในระบบแล้ว")
                update_dict["node_id"] = update_data.node_id

            if update_data.vendor is not None:
                update_dict["vendor"] = update_data.vendor.value


            # NETCONF Connection Fields
            if update_data.netconf_host is not None:
                update_dict["netconf_host"] = update_data.netconf_host

            if update_data.netconf_port is not None:
                update_dict["netconf_port"] = update_data.netconf_port

            if update_data.netconf_username is not None:
                update_dict["netconf_username"] = update_data.netconf_username

            if update_data.netconf_password is not None:
                update_dict["netconf_password"] = update_data.netconf_password

            #Validate foreign keys
            if foreign_keys_to_validate:
                await self._validate_foreign_keys(foreign_keys_to_validate)

            if not update_dict:
                raise ValueError("ไม่มีข้อมูลที่จะอัปเดต")

            #อัปเดตข้อมูล
            updated_device = await self.prisma.devicenetwork.update(
                where={"id": device_id},
                data=update_dict,
                include={
                    "tags": True,
                    "operatingSystem": True,
                    "localSite": True,
                    "configuration_template": True
                }
            )

            return self._build_device_response(updated_device)

        except Exception as e:
            print(f"Error updating device: {e}")
            raise e

    async def delete_device(self, device_id: str) -> bool:
        #ลบ Device Network
        try:
            existing_device = await self.prisma.devicenetwork.find_unique(
                where={"id": device_id}
            )

            if not existing_device:
                raise ValueError("ไม่พบ Device Network ที่ต้องการลบ")

            await self.prisma.devicenetwork.delete(where={"id": device_id})
            return True

        except Exception as e:
            print(f"Error deleting device: {e}")
            raise e

    async def assign_tags(self, device_id: str, tag_ids: list[str]) -> Optional[DeviceNetworkResponse]:
        #เพิ่ม tags ให้กับ Device
        try:
            #ตรวจสอบว่า device มีอยู่จริง
            device = await self.prisma.devicenetwork.find_unique(where={"id": device_id})
            if not device:
                raise ValueError("ไม่พบ Device Network")

            #ตรวจสอบว่า tags มีอยู่จริงทั้งหมด
            for tag_id in tag_ids:
                tag = await self.prisma.tag.find_unique(where={"tag_id": tag_id})
                if not tag:
                    raise ValueError(f"ไม่พบ Tag ID: {tag_id}")

            #เชื่อมโยง tags กับ device
            updated_device = await self.prisma.devicenetwork.update(
                where={"id": device_id},
                data={
                    "tags": {
                        "connect": [{"tag_id": tag_id} for tag_id in tag_ids]
                    }
                },
                include={
                    "tags": True,
                    "operatingSystem": True,
                    "localSite": True,
                    "configuration_template": True
                }
            )

            return self._build_device_response(updated_device)

        except Exception as e:
            print(f"Error assigning tags: {e}")
            raise e

    async def remove_tags(self, device_id: str, tag_ids: list[str]) -> Optional[DeviceNetworkResponse]:
        #ลบ tags ออกจาก Device
        try:
            #ตรวจสอบว่า device มีอยู่จริง
            device = await self.prisma.devicenetwork.find_unique(where={"id": device_id})
            if not device:
                raise ValueError("ไม่พบ Device Network")

            #ตัดการเชื่อมโยง tags
            updated_device = await self.prisma.devicenetwork.update(
                where={"id": device_id},
                data={
                    "tags": {
                        "disconnect": [{"tag_id": tag_id} for tag_id in tag_ids]
                    }
                },
                include={
                    "tags": True,
                    "operatingSystem": True,
                    "localSite": True,
                    "configuration_template": True
                }
            )

            return self._build_device_response(updated_device)

        except Exception as e:
            print(f"Error removing tags: {e}")
            raise e

