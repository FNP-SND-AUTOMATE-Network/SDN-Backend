from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any
from app.database import get_db
from app.api.users import get_current_user
from app.services.device_credentials_service import DeviceCredentialsService
from app.models.device_credentials import (
    DeviceCredentialsUpdate,
    DeviceCredentialsResponse,
    DeviceCredentialsCreateResponse,
    DeviceCredentialsUpdateResponse,
    DeviceCredentialsDeleteResponse,
    DeviceCredentialsVerifyRequest,
    DeviceCredentialsCreate
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/device-credentials", tags=["Device Network Credentials"])


@router.get(
    "/",
    response_model=DeviceCredentialsResponse,
    summary="Get Device Network Credentials",
    description="Get Device Network Credentials of current user (does not show password, but shows if it exists)"
)
async def get_device_credentials(
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        device_creds_svc = DeviceCredentialsService(db)
        
        device_credentials = await device_creds_svc.get_device_credentials(current_user["id"])
        
        if not device_credentials:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device Network Credentials not found"
            )
        
        return device_credentials
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_device_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error in get_device_credentials"
        )


@router.post(
    "/",
    response_model=DeviceCredentialsCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new Device Network Credentials",
    description="Create new Device Network Credentials for current user"
)
async def create_device_credentials(
    data: DeviceCredentialsCreate,
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        device_creds_svc = DeviceCredentialsService(db)
        
        device_credentials = await device_creds_svc.create_device_credentials(
            user_id=current_user["id"],
            data=data
        )
        
        if not device_credentials:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create Device Network Credentials"
            )
        
        return DeviceCredentialsCreateResponse(
            message="Device Network Credentials created successfully",
            device_credentials=device_credentials
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_device_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error in create_device_credentials"
        )


@router.put(
    "/",
    response_model=DeviceCredentialsUpdateResponse,
    summary="Update Device Network Credentials",
    description="Update Device Network Credentials of current user"
)
async def update_device_credentials(
    data: DeviceCredentialsUpdate,
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        device_creds_svc = DeviceCredentialsService(db)
        
        device_credentials = await device_creds_svc.update_device_credentials(
            user_id=current_user["id"],
            data=data
        )
        
        if not device_credentials:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update Device Network Credentials"
            )
        
        return DeviceCredentialsUpdateResponse(
            message="Device Network Credentials updated successfully",
            device_credentials=device_credentials
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_device_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error in update_device_credentials"
        )


@router.delete(
    "/",
    response_model=DeviceCredentialsDeleteResponse,
    summary="Delete Device Network Credentials",
    description="Delete Device Network Credentials of current user"
)
async def delete_device_credentials(
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        device_creds_svc = DeviceCredentialsService(db)
        
        success = await device_creds_svc.delete_device_credentials(current_user["id"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete Device Network Credentials"
            )
        
        return DeviceCredentialsDeleteResponse(
            message="Device Network Credentials deleted successfully"
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_device_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error in delete_device_credentials"
        )


@router.post(
    "/verify",
    summary="Verify Device Network Credentials",
    description="Verify Device Network Credentials for device access"
)
async def verify_device_credentials(
    credentials: DeviceCredentialsVerifyRequest,
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        device_creds_svc = DeviceCredentialsService(db)
        
        is_valid = await device_creds_svc.verify_device_credentials(
            user_id=current_user["id"],
            username=credentials.username,
            password=credentials.password
        )
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Device Network Credentials"
            )
        
        return {
            "message": "Device Network Credentials is valid",
            "valid": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in verify_device_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error in verify_device_credentials"
        )
