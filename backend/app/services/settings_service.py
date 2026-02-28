"""
System Settings Service
Service สำหรับจัดการ Configuration ที่เก็บใน Database พร้อมระบบ In-Memory Cache
"""
from typing import Dict, Any, Optional
from datetime import datetime
import json
from app.database import get_prisma_client
from app.core.config import settings
from app.core.logging import logger
import asyncio

class SettingsService:
    # In-memory cache
    _odl_config_cache: Optional[Dict[str, Any]] = None
    _is_initializing = False

    @classmethod
    async def get_odl_config(cls) -> Dict[str, Any]:
        """ดึงข้อมูล ODL Config (ดึงจาก Cache ถ้ามี ถ้าไม่มีดึงจาก DB)"""
        if cls._odl_config_cache is not None:
            return cls._odl_config_cache
            
        return await cls._load_and_cache_odl_config()

    @classmethod
    async def _load_and_cache_odl_config(cls) -> Dict[str, Any]:
        """โหลดข้อมูลจาก .env เนื่องจาก SystemSettings table ถูกลบไปแล้ว"""
        # ป้องกัน Race Condition ตอน Startup มีหลาย request เข้ามาพร้อมกัน
        if cls._is_initializing:
            await asyncio.sleep(0.5)
            if cls._odl_config_cache is not None:
                return cls._odl_config_cache

        cls._is_initializing = True
        try:
            default_config = cls._get_default_env_config()
            cls._odl_config_cache = default_config
            return cls._odl_config_cache
            
        finally:
            cls._is_initializing = False

    @classmethod
    async def update_odl_config(cls, base_url: str, username: str, password: str, timeout: float = 10.0, retry: int = 1) -> Dict[str, Any]:
        """อัปเดต ODL Config ใน Database และ Cache"""
        new_config = {
            "ODL_BASE_URL": base_url.rstrip("/"),
            "ODL_USERNAME": username,
            "ODL_PASSWORD": password,
            "ODL_TIMEOUT_SEC": timeout,
            "ODL_RETRY": retry
        }

        prisma = get_prisma_client()
        
        # Upsert
        existing = await prisma.systemsettings.find_unique(where={"key": "odl_config"})
        if existing:
            await prisma.systemsettings.update(
                where={"key": "odl_config"},
                data={"value": json.dumps(new_config)}
            )
        else:
            await prisma.systemsettings.create(
                data={
                    "key": "odl_config",
                    "value": json.dumps(new_config),
                    "description": "OpenDaylight Connection Configuration"
                }
            )

        # อัปเดต Cache
        cls._odl_config_cache = new_config
        logger.info(f"ODL configuration updated. New base_url: {base_url}")
        
        return new_config

    @staticmethod
    def _get_default_env_config() -> Dict[str, Any]:
        """ค่าเริ่มต้นจาก .env"""
        return {
            "ODL_BASE_URL": settings.ODL_BASE_URL.rstrip("/"),
            "ODL_USERNAME": settings.ODL_USERNAME,
            "ODL_PASSWORD": settings.ODL_PASSWORD,
            "ODL_TIMEOUT_SEC": settings.ODL_TIMEOUT_SEC,
            "ODL_RETRY": settings.ODL_RETRY
        }
