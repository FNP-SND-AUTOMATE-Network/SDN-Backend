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

    # ── Security Settings ────────────────────────────────────────────────────
    # APP_ENV: "development" | "production"
    # ใน production ให้ตั้ง SECURE_COOKIES=true และ APP_ENV=production
    APP_ENV: str = os.getenv("APP_ENV", "development")

    # SECRET_KEY: Required for JWT signing — app will fail-fast if missing
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")

    # JWT settings (centralised — previously scattered across UserService)
    JWT_ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    # SECURE_COOKIES: ถ้า True จะตั้ง Secure flag บน auth cookies (HTTPS เท่านั้น)
    # เปลี่ยนเป็น true เมื่อ deploy บน HTTPS
    SECURE_COOKIES: bool = os.getenv("SECURE_COOKIES", "false").lower() == "true"

    # CSRF_ENABLED: ถ้า False จะ bypass CSRF check ทั้งหมด (ใช้ได้แต่ dev เท่านั้น)
    # ควรเปิดไว้เสมอเมื่อ deploy (default: true)
    CSRF_ENABLED: bool = os.getenv("CSRF_ENABLED", "true").lower() == "true"

    # CORS: Allowed origins (comma-separated). Defaults to localhost for dev.
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")


settings = Settings()

# ── Fail-fast validation ─────────────────────────────────────────────────────
if not settings.SECRET_KEY:
    raise RuntimeError(
        "FATAL: SECRET_KEY environment variable is not set. "
        "JWT tokens cannot be signed without it. "
        "Set SECRET_KEY in your .env file or environment."
    )
