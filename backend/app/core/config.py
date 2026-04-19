"""
Centralized Configuration
ศูนย์กลางการตั้งค่าทั้งหมดของแอปพลิเคชัน

หน้าที่หลัก:
- โหลดค่า Environment Variables จากไฟล์ .env (อยู่ที่ backend/.env)
- กำหนดค่า Default สำหรับทุกการตั้งค่า
- ใช้ Pydantic BaseModel เพื่อ validate ค่าที่โหลดมา
- Export เป็น Singleton `settings` สำหรับใช้ทั่วทั้งแอป

กลุ่มการตั้งค่า:
- ODL: การเชื่อมต่อ OpenDaylight Controller (URL, Credentials, Timeout, Retry)
- SYNC: Background Sync สำหรับ Device/Topology (เปิด/ปิด, Interval)
- CHATOPS: Slack Integration สำหรับแจ้งเตือน (Webhook URL, เปิด/ปิด)
- ZABBIX: Zabbix Monitoring Integration (API URL, Token)
"""

from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

import os
from pydantic import BaseModel

class Settings(BaseModel):
    ODL_BASE_URL: str = os.getenv("ODL_BASE_URL", "http://127.0.0.1:8181")
    ODL_USERNAME: str = os.getenv("ODL_USERNAME", "admin")
    ODL_PASSWORD: str = os.getenv("ODL_PASSWORD", "admin")
    ODL_TIMEOUT_SEC: float = float(os.getenv("ODL_TIMEOUT_SEC", "10"))
    ODL_RETRY: int = int(os.getenv("ODL_RETRY", "1"))

    # Background Sync Settings
    SYNC_ENABLED: bool = os.getenv("SYNC_ENABLED", "true").lower() == "true"
    SYNC_DEVICE_INTERVAL_SEC: int = int(os.getenv("SYNC_DEVICE_INTERVAL_SEC", "60"))   # Device status sync
    SYNC_TOPOLOGY_INTERVAL_SEC: int = int(os.getenv("SYNC_TOPOLOGY_INTERVAL_SEC", "300"))  # Topology sync

    # ChatOps / Slack Integration
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
    CHATOPS_ENABLED: bool = os.getenv("CHATOPS_ENABLED", "true").lower() == "true"

    # Zabbix Integration (shared token สำหรับทั้ง webhook + dashboard API)
    ZABBIX_WEBHOOK_TOKEN: str = os.getenv("ZABBIX_WEBHOOK_TOKEN", "")  # ถ้าว่าง = ไม่ต้อง auth
    ZABBIX_API_URL: str = os.getenv("ZABBIX_API_URL", "http://zabbix-web:8080/api_jsonrpc.php")
    ZABBIX_API_TOKEN: str = os.getenv("ZABBIX_API_TOKEN", "")

settings = Settings()
