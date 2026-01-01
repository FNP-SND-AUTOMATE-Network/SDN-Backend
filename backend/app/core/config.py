from pathlib import Path
from dotenv import load_dotenv

# ✅ ชี้ path .env แบบแน่นอน (อยู่ที่ backend/.env)
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

settings = Settings()
