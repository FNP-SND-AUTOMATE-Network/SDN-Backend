from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, Optional, List
from app.database import get_db
from app.api.users import get_current_user
from app.services.interface_service import InterfaceService
from app.models.interface import (
    InterfaceCreate,
    InterfaceUpdate,
    InterfaceResponse,
    InterfaceListResponse,
    InterfaceCreateResponse,
    InterfaceUpdateResponse,
    InterfaceDeleteResponse,
    InterfaceStatus,
    InterfaceType
)
from prisma import Prisma

router = APIRouter(prefix="/interfaces", tags=["Network Interfaces"])

def get_interface_service(db: Prisma = Depends(get_db)) -> InterfaceService:
    return InterfaceService(db)

@router.get("/", response_model=InterfaceListResponse)
async def get_interfaces(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    device_id: Optional[str] = Query(None, description="Filter by Device ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    interface_type: Optional[str] = Query(None, description="Filter by interface type"),
    search: Optional[str] = Query(None, description="Search by name, label, or description"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    try:
        interfaces, total = await interface_svc.get_interfaces(
            page=page,
            page_size=page_size,
            device_id=device_id,
            status=status,
            interface_type=interface_type,
            search=search
        )

        return InterfaceListResponse(
            total=total,
            page=page,
            page_size=page_size,
            interfaces=interfaces
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching interfaces: {str(e)}"
        )

@router.get("/device/{device_id}", response_model=List[InterfaceResponse])
async def get_interfaces_by_device(
    device_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    try:
        interfaces = await interface_svc.get_interfaces_by_device(device_id)
        return interfaces

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching interfaces by device: {str(e)}"
        )

@router.get("/{interface_id}", response_model=InterfaceResponse)
async def get_interface(
    interface_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    try:
        interface = await interface_svc.get_interface_by_id(interface_id)
        
        if not interface:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interface not found"
            )
        
        return interface

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching interface: {str(e)}"
        )

@router.post("/", response_model=InterfaceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_interface(
    interface_data: InterfaceCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to create an interface"
            )

        interface = await interface_svc.create_interface(interface_data)
        
        if not interface:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create interface"
            )

        return InterfaceCreateResponse(
            message="Interface created successfully",
            interface=interface
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
            detail=f"Error creating interface: {str(e)}"
        )

@router.put("/{interface_id}", response_model=InterfaceUpdateResponse)
async def update_interface(
    interface_id: str,
    update_data: InterfaceUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update an interface"
            )

        interface = await interface_svc.update_interface(interface_id, update_data)
        
        if not interface:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update interface"
            )

        return InterfaceUpdateResponse(
            message="Interface updated successfully",
            interface=interface
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
            detail=f"Error updating interface: {str(e)}"
        )

@router.delete("/{interface_id}", response_model=InterfaceDeleteResponse)
async def delete_interface(
    interface_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    interface_svc: InterfaceService = Depends(get_interface_service)
):
    try:
        if current_user["role"] not in ["ENGINEER", "ADMIN", "OWNER"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete an interface"
            )

        success = await interface_svc.delete_interface(interface_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete interface"
            )

        return InterfaceDeleteResponse(
            message="Interface deleted successfully"
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
            detail=f"Error deleting interface: {str(e)}"
        )

