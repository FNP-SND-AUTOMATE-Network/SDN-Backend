from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Optional, List
from app.models.ipam import (
    SubnetResponse, SubnetListResponse,
    IpAddressCreateRequest, IpAddressAssignRequest, IpAddressUpdateRequest, 
    IpAddressResponse, IpAddressDetailResponse, IpAddressListResponse,
    DeviceIpAssignRequest, InterfaceIpAssignRequest, IpAssignmentResponse,
    SyncRequest, SyncResponse,
    SubnetCreateRequest, SubnetUpdateRequest, SubnetDetailResponse, SubnetUsageResponse,
    SectionResponse, SectionListResponse, SectionCreateRequest, SectionUpdateRequest
)
from app.services.phpipam_service import PhpipamService
from app.database import get_prisma_client, is_prisma_client_ready
from app.api.users import get_current_user

router = APIRouter(prefix="/ipam", tags=["IP Address Management"])

# Services
phpipam_service = None

def get_phpipam_service():
    """Get initialized phpIPAM service"""
    global phpipam_service
    
    if phpipam_service is None:
        phpipam_service = PhpipamService()
    
    return phpipam_service


def check_engineer_permission(current_user: dict):
    """ตรวจสอบว่าเป็น ENGINEER, ADMIN หรือ OWNER"""
    if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only ENGINEER, ADMIN, or OWNER can manage IP addresses"
        )


# ========= Subnet Endpoints =========

@router.get("/subnets", response_model=SubnetListResponse)
async def get_subnets(
    current_user: dict = Depends(get_current_user)
):
    """ดึงรายการ subnets ทั้งหมดจาก phpIPAM"""
    try:
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        subnets = await phpipam_svc.get_subnets()
        
        subnet_list = [
            SubnetResponse(
                id=str(subnet.get("id")),
                subnet=subnet.get("subnet", ""),
                mask=subnet.get("mask", ""),
                description=subnet.get("description"),
                section_id=str(subnet.get("sectionId")) if subnet.get("sectionId") else None,
                vlan_id=str(subnet.get("vlanId")) if subnet.get("vlanId") else None
            )
            for subnet in subnets
        ]
        
        return SubnetListResponse(
            subnets=subnet_list,
            total=len(subnet_list)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching subnets: {str(e)}"
        )


@router.get("/subnets/{subnet_id}/addresses", response_model=IpAddressListResponse)
async def get_subnet_addresses(
    subnet_id: str,
    current_user: dict = Depends(get_current_user)
):
    """ดึงรายการ IP addresses ใน subnet"""
    try:
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        addresses = await phpipam_svc.get_subnet_addresses(subnet_id)
        
        address_list = [
            IpAddressResponse(
                id=str(addr.get("id")),
                ip=addr.get("ip", ""),
                subnet_id=str(addr.get("subnetId", "")),
                hostname=addr.get("hostname"),
                description=addr.get("description"),
                mac=addr.get("mac"),
                phpipam_id=str(addr.get("id"))
            )
            for addr in addresses
        ]
        
        return IpAddressListResponse(
            addresses=address_list,
            total=len(address_list)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching addresses: {str(e)}"
        )


# ========= Device IP Management =========

@router.post("/devices/{device_id}/assign-ip", response_model=IpAssignmentResponse)
async def assign_ip_to_device(
    device_id: str,
    request: DeviceIpAssignRequest,
    current_user: dict = Depends(get_current_user)
):
    """Assign IP address ให้กับ device"""
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        prisma = get_prisma_client()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        # ดึงข้อมูล device
        device = await prisma.devicenetwork.find_unique(where={"id": device_id})
        if not device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found"
            )
        
        # Assign IP จาก phpIPAM
        ip_data = await phpipam_svc.assign_ip_to_device(
            device_name=device.device_name,
            subnet_id=request.subnet_id,
            mac_address=device.mac_address,
            description=request.description or f"Device: {device.device_name}"
        )
        
        if not ip_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to assign IP from phpIPAM"
            )
        
        # อัปเดต device ใน database
        await prisma.devicenetwork.update(
            where={"id": device_id},
            data={
                "phpipam_address_id": str(ip_data.get("id")),
                "ip_address": ip_data.get("ip")
            }
        )
        
        return IpAssignmentResponse(
            message="IP assigned successfully",
            ip_address=ip_data.get("ip", ""),
            subnet_id=request.subnet_id,
            phpipam_address_id=str(ip_data.get("id")),
            device_id=device_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error assigning IP: {str(e)}"
        )


@router.delete("/devices/{device_id}/release-ip")
async def release_device_ip(
    device_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        prisma = get_prisma_client()
        
        # ดึงข้อมูล device
        device = await prisma.devicenetwork.find_unique(where={"id": device_id})
        if not device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found"
            )
        
        if not device.phpipam_address_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Device has no IP assigned"
            )
        
        # Release IP จาก phpIPAM
        if phpipam_svc.enabled:
            success = await phpipam_svc.release_ip(device.phpipam_address_id)
            if not success:
                print(f"Warning: Failed to release IP {device.phpipam_address_id} from phpIPAM")
        
        # อัปเดต device
        await prisma.devicenetwork.update(
            where={"id": device_id},
            data={
                "phpipam_address_id": None,
                "ip_address": None
            }
        )
        
        return {"message": "IP released successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error releasing IP: {str(e)}"
        )


# ========= Interface IP Management =========

@router.post("/interfaces/{interface_id}/assign-ip", response_model=IpAssignmentResponse)
async def assign_ip_to_interface(
    interface_id: str,
    request: InterfaceIpAssignRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        prisma = get_prisma_client()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        # ดึงข้อมูล interface และ device
        interface = await prisma.interface.find_unique(
            where={"id": interface_id},
            include={"device": True}
        )
        if not interface:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interface not found"
            )
        
        # Assign IP จาก phpIPAM
        hostname = f"{interface.device.device_name}-{interface.name}"
        ip_data = await phpipam_svc.assign_ip_to_device(
            device_name=hostname,
            subnet_id=request.subnet_id,
            description=request.description or f"Interface: {hostname}"
        )
        
        if not ip_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to assign IP from phpIPAM"
            )
        
        # ดึงข้อมูล subnet เพื่อเอา subnet mask
        subnet = await phpipam_svc.get_subnet(request.subnet_id)
        subnet_mask = f"/{subnet.get('mask')}" if subnet else None
        
        # อัปเดต interface ใน database
        await prisma.interface.update(
            where={"id": interface_id},
            data={
                "phpipam_address_id": str(ip_data.get("id")),
                "ip_address": ip_data.get("ip"),
                "subnet_mask": subnet_mask
            }
        )
        
        return IpAssignmentResponse(
            message="IP assigned successfully",
            ip_address=ip_data.get("ip", ""),
            subnet_id=request.subnet_id,
            phpipam_address_id=str(ip_data.get("id")),
            interface_id=interface_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error assigning IP: {str(e)}"
        )


@router.delete("/interfaces/{interface_id}/release-ip")
async def release_interface_ip(
    interface_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        prisma = get_prisma_client()
        
        # ดึงข้อมูล interface
        interface = await prisma.interface.find_unique(where={"id": interface_id})
        if not interface:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interface not found"
            )
        
        if not interface.phpipam_address_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Interface has no IP assigned"
            )
        
        # Release IP จาก phpIPAM
        if phpipam_svc.enabled:
            success = await phpipam_svc.release_ip(interface.phpipam_address_id)
            if not success:
                print(f"Warning: Failed to release IP {interface.phpipam_address_id} from phpIPAM")
        
        # อัปเดต interface
        await prisma.interface.update(
            where={"id": interface_id},
            data={
                "phpipam_address_id": None,
                "ip_address": None,
                "subnet_mask": None,
                "gateway": None
            }
        )
        
        return {"message": "IP released successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error releasing IP: {str(e)}"
        )


# ========= Subnet CRUD Endpoints =========

@router.post("/subnets", response_model=SubnetDetailResponse)
async def create_subnet(
    request: SubnetCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        # สร้าง subnet - ส่งเฉพาะ parameters ที่ phpIPAM รองรับ
        subnet_data = await phpipam_svc.create_subnet(
            subnet=request.subnet,
            mask=request.mask,
            section_id=request.section_id,
            description=request.description,
            vlan_id=request.vlan_id,
            master_subnet_id=request.master_subnet_id
        )
        
        if not subnet_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create subnet in phpIPAM"
            )
        
        return SubnetDetailResponse(
            id=str(subnet_data.get("id")),
            subnet=subnet_data.get("subnet", ""),
            mask=subnet_data.get("mask", ""),
            section_id=str(subnet_data.get("sectionId", "")),
            description=subnet_data.get("description"),
            vlan_id=str(subnet_data.get("vlanId")) if subnet_data.get("vlanId") else None,
            master_subnet_id=str(subnet_data.get("masterSubnetId")) if subnet_data.get("masterSubnetId") else None,
            permissions=subnet_data.get("permissions"),
            show_name=subnet_data.get("showName")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating subnet: {str(e)}"
        )


@router.get("/subnets/{subnet_id}", response_model=SubnetDetailResponse)
async def get_subnet_detail(
    subnet_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        subnet_data = await phpipam_svc.get_subnet(subnet_id)
        
        if not subnet_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subnet not found"
            )
        
        return SubnetDetailResponse(
            id=str(subnet_data.get("id")),
            subnet=subnet_data.get("subnet", ""),
            mask=subnet_data.get("mask", ""),
            section_id=str(subnet_data.get("sectionId", "")),
            description=subnet_data.get("description"),
            vlan_id=str(subnet_data.get("vlanId")) if subnet_data.get("vlanId") else None,
            master_subnet_id=str(subnet_data.get("masterSubnetId")) if subnet_data.get("masterSubnetId") else None,
            permissions=subnet_data.get("permissions"),
            show_name=subnet_data.get("showName")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching subnet: {str(e)}"
        )


@router.patch("/subnets/{subnet_id}", response_model=SubnetDetailResponse)
async def update_subnet(
    subnet_id: str,
    request: SubnetUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        # สร้าง dict ของ fields ที่ต้องการ update
        update_data = {}
        if request.subnet is not None:
            update_data["subnet"] = request.subnet
        if request.mask is not None:
            update_data["mask"] = request.mask
        if request.description is not None:
            update_data["description"] = request.description
        if request.vlan_id is not None:
            update_data["vlanId"] = request.vlan_id
        if request.master_subnet_id is not None:
            update_data["masterSubnetId"] = request.master_subnet_id
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )
        
        subnet_data = await phpipam_svc.update_subnet(subnet_id, **update_data)
        
        if not subnet_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update subnet"
            )
        
        return SubnetDetailResponse(
            id=str(subnet_data.get("id")),
            subnet=subnet_data.get("subnet", ""),
            mask=subnet_data.get("mask", ""),
            section_id=str(subnet_data.get("sectionId", "")),
            description=subnet_data.get("description"),
            vlan_id=str(subnet_data.get("vlanId")) if subnet_data.get("vlanId") else None,
            master_subnet_id=str(subnet_data.get("masterSubnetId")) if subnet_data.get("masterSubnetId") else None,
            permissions=subnet_data.get("permissions"),
            show_name=subnet_data.get("showName")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating subnet: {str(e)}"
        )


@router.delete("/subnets/{subnet_id}")
async def delete_subnet(
    subnet_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        success = await phpipam_svc.delete_subnet(subnet_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete subnet"
            )
        
        return {"message": "Subnet deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting subnet: {str(e)}"
        )


@router.get("/subnets/{subnet_id}/usage", response_model=SubnetUsageResponse)
async def get_subnet_usage(
    subnet_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        usage_data = await phpipam_svc.get_subnet_usage(subnet_id)
        
        if not usage_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usage data not found"
            )
        
        return SubnetUsageResponse(
            used=int(usage_data.get("used", 0)),
            maxhosts=int(usage_data.get("maxhosts", 0)),
            freehosts=int(usage_data.get("freehosts", 0)),
            freehosts_percent=float(usage_data.get("freehosts_percent", 0)),
            Offline_percent=float(usage_data.get("Offline_percent", 0)) if usage_data.get("Offline_percent") else None,
            Used_percent=float(usage_data.get("Used_percent", 0)),
            Reserved_percent=float(usage_data.get("Reserved_percent", 0)) if usage_data.get("Reserved_percent") else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching usage: {str(e)}"
        )


# ========= Sections Endpoints =========

@router.get("/sections", response_model=SectionListResponse)
async def get_sections(
    current_user: dict = Depends(get_current_user)
):
    """ดึงรายการ sections ทั้งหมด"""
    try:
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        sections = await phpipam_svc.get_sections()
        
        section_list = [
            SectionResponse(
                id=str(section.get("id")),
                name=section.get("name", ""),
                description=section.get("description"),
                master_section=str(section.get("masterSection")) if section.get("masterSection") else None,
                permissions=section.get("permissions"),
                strict_mode=section.get("strictMode"),
                subnet_ordering=section.get("subnetOrdering"),
                order=section.get("order"),
                show_vlan_in_subnet_listing=section.get("showVLAN"),
                show_vrf_in_subnet_listing=section.get("showVRF")
            )
            for section in sections
        ]
        
        return SectionListResponse(
            sections=section_list,
            total=len(section_list)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching sections: {str(e)}"
        )


@router.post("/sections", response_model=SectionResponse)
async def create_section(
    request: SectionCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        # สร้าง section - ส่งเฉพาะ parameters ที่จำเป็นและมี default values
        section_data = await phpipam_svc.create_section(
            name=request.name,
            description=request.description,
            master_section=request.master_section,
            strictMode=request.strict_mode if request.strict_mode else "1",  # Default: strict mode on
            showVLAN=1 if request.show_vlan_in_subnet_listing else 0,
            showVRF=1 if request.show_vrf_in_subnet_listing else 0
        )
        
        if not section_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create section in phpIPAM"
            )
        
        return SectionResponse(
            id=str(section_data.get("id")),
            name=section_data.get("name", ""),
            description=section_data.get("description"),
            master_section=str(section_data.get("masterSection")) if section_data.get("masterSection") else None,
            permissions=section_data.get("permissions"),
            strict_mode=section_data.get("strictMode"),
            subnet_ordering=section_data.get("subnetOrdering"),
            order=section_data.get("order"),
            show_vlan_in_subnet_listing=section_data.get("showVLAN"),
            show_vrf_in_subnet_listing=section_data.get("showVRF")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating section: {str(e)}"
        )


@router.patch("/sections/{section_id}", response_model=SectionResponse)
async def update_section(
    section_id: str,
    request: SectionUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        # สร้าง dict ของ fields ที่ต้องการ update
        update_data = {}
        if request.name is not None:
            update_data["name"] = request.name
        if request.description is not None:
            update_data["description"] = request.description
        if request.master_section is not None:
            update_data["masterSection"] = request.master_section
        if request.permissions is not None:
            update_data["permissions"] = request.permissions
        if request.strict_mode is not None:
            update_data["strictMode"] = request.strict_mode
        if request.subnet_ordering is not None:
            update_data["subnetOrdering"] = request.subnet_ordering
        if request.order is not None:
            update_data["order"] = request.order
        if request.show_vlan_in_subnet_listing is not None:
            update_data["showVLAN"] = 1 if request.show_vlan_in_subnet_listing else 0
        if request.show_vrf_in_subnet_listing is not None:
            update_data["showVRF"] = 1 if request.show_vrf_in_subnet_listing else 0
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )
        
        section_data = await phpipam_svc.update_section(section_id, **update_data)
        
        if not section_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update section"
            )
        
        return SectionResponse(
            id=str(section_data.get("id")),
            name=section_data.get("name", ""),
            description=section_data.get("description"),
            master_section=str(section_data.get("masterSection")) if section_data.get("masterSection") else None,
            permissions=section_data.get("permissions"),
            strict_mode=section_data.get("strictMode"),
            subnet_ordering=section_data.get("subnetOrdering"),
            order=section_data.get("order"),
            show_vlan_in_subnet_listing=section_data.get("showVLAN"),
            show_vrf_in_subnet_listing=section_data.get("showVRF")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating section: {str(e)}"
        )


@router.delete("/sections/{section_id}")
async def delete_section(
    section_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        success = await phpipam_svc.delete_section(section_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete section"
            )
        
        return {"message": "Section deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting section: {str(e)}"
        )


@router.get("/sections/{section_id}/subnets", response_model=SubnetListResponse)
async def get_section_subnets(
    section_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        subnets = await phpipam_svc.get_section_subnets(section_id)
        
        # Filter เฉพาะ parent subnets (ที่ไม่มี master_subnet_id หรือเป็น "0")
        parent_subnets = [
            subnet for subnet in subnets
            if not subnet.get("masterSubnetId") or subnet.get("masterSubnetId") == "0"
        ]
        
        subnet_list = [
            SubnetResponse(
                id=str(subnet.get("id")),
                subnet=subnet.get("subnet", ""),
                mask=subnet.get("mask", ""),
                description=subnet.get("description"),
                section_id=str(subnet.get("sectionId")) if subnet.get("sectionId") else None,
                vlan_id=str(subnet.get("vlanId")) if subnet.get("vlanId") else None,
                master_subnet_id=None  # Parent subnets ไม่มี master
            )
            for subnet in parent_subnets
        ]
        
        return SubnetListResponse(
            subnets=subnet_list,
            total=len(subnet_list)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching section subnets: {str(e)}"
        )


# ========= IP Address CRUD Endpoints =========

@router.post("/addresses", response_model=IpAddressDetailResponse)
async def create_ip_address(
    request: IpAddressCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """สร้าง IP address ใหม่"""
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        # Create IP address
        ip_data = await phpipam_svc.create_ip_address(
            subnet_id=request.subnet_id,
            ip_address=request.ip_address,
            hostname=request.hostname,
            description=request.description,
            mac_address=request.mac_address,
            is_gateway=request.is_gateway,
            tag=request.tag
        )
        
        if not ip_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create IP address"
            )
        
        return IpAddressDetailResponse(
            id=str(ip_data.get("id")),
            ip=ip_data.get("ip", ""),
            subnet_id=str(ip_data.get("subnetId", "")),
            hostname=ip_data.get("hostname"),
            description=ip_data.get("description"),
            mac=ip_data.get("mac"),
            is_gateway=ip_data.get("is_gateway"),
            tag=ip_data.get("tag")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating IP address: {str(e)}"
        )


@router.get("/addresses/{address_id}", response_model=IpAddressDetailResponse)
async def get_ip_address(
    address_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        ip_data = await phpipam_svc.get_ip_address(address_id)
        
        if not ip_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="IP address not found"
            )
        
        return IpAddressDetailResponse(
            id=str(ip_data.get("id")),
            ip=ip_data.get("ip", ""),
            subnet_id=str(ip_data.get("subnetId", "")),
            hostname=ip_data.get("hostname"),
            description=ip_data.get("description"),
            mac=ip_data.get("mac"),
            is_gateway=ip_data.get("is_gateway"),
            tag=ip_data.get("tag")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching IP address: {str(e)}"
        )


@router.patch("/addresses/{address_id}", response_model=IpAddressDetailResponse)
async def update_ip_address(
    address_id: str,
    request: IpAddressUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        # Build update data
        update_data = {}
        if request.hostname is not None:
            update_data["hostname"] = request.hostname
        if request.description is not None:
            update_data["description"] = request.description
        if request.mac_address is not None:
            update_data["mac"] = request.mac_address
        if request.is_gateway is not None:
            update_data["is_gateway"] = request.is_gateway
        if request.tag is not None:
            update_data["tag"] = request.tag
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )
        
        ip_data = await phpipam_svc.update_ip_address(address_id, **update_data)
        
        if not ip_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update IP address"
            )
        
        return IpAddressDetailResponse(
            id=str(ip_data.get("id")),
            ip=ip_data.get("ip", ""),
            subnet_id=str(ip_data.get("subnetId", "")),
            hostname=ip_data.get("hostname"),
            description=ip_data.get("description"),
            mac=ip_data.get("mac"),
            is_gateway=ip_data.get("is_gateway"),
            tag=ip_data.get("tag")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating IP address: {str(e)}"
        )


@router.delete("/addresses/{address_id}")
async def delete_ip_address(
    address_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        check_engineer_permission(current_user)
        
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        success = await phpipam_svc.delete_ip_address(address_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete IP address"
            )
        
        return {"message": "IP address deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting IP address: {str(e)}"
        )


@router.get("/addresses/search", response_model=IpAddressListResponse)
async def search_ip_addresses(
    q: str = Query(..., description="Search query (IP address or hostname)"),
    current_user: dict = Depends(get_current_user)
):
    try:
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        results = await phpipam_svc.search_ip(q)
        
        address_list = [
            IpAddressResponse(
                id=str(addr.get("id")),
                ip=addr.get("ip", ""),
                subnet_id=str(addr.get("subnetId", "")),
                hostname=addr.get("hostname"),
                description=addr.get("description"),
                mac=addr.get("mac"),
                phpipam_id=str(addr.get("id"))
            )
            for addr in results
        ]
        
        return IpAddressListResponse(
            addresses=address_list,
            total=len(address_list)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching IP addresses: {str(e)}"
        )


@router.get("/subnets/{subnet_id}/children", response_model=SubnetListResponse)
async def get_subnet_children(
    subnet_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        phpipam_svc = get_phpipam_service()
        
        if not phpipam_svc.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="phpIPAM integration is not enabled"
            )
        
        # Get all subnets
        all_subnets = await phpipam_svc.get_subnets()
        
        # Filter child subnets
        child_subnets = [
            subnet for subnet in all_subnets
            if str(subnet.get("masterSubnetId")) == subnet_id and subnet.get("masterSubnetId") != "0"
        ]
        
        subnet_list = [
            SubnetResponse(
                id=str(subnet.get("id")),
                subnet=subnet.get("subnet", ""),
                mask=subnet.get("mask", ""),
                description=subnet.get("description"),
                section_id=str(subnet.get("sectionId")) if subnet.get("sectionId") else None,
                vlan_id=str(subnet.get("vlanId")) if subnet.get("vlanId") else None,
                master_subnet_id=str(subnet.get("masterSubnetId")) if subnet.get("masterSubnetId") else None
            )
            for subnet in child_subnets
        ]
        
        return SubnetListResponse(
            subnets=subnet_list,
            total=len(subnet_list)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching child subnets: {str(e)}"
        )
