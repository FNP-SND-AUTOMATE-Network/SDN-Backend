from fastapi import APIRouter
from pydantic import BaseModel

class HealthOut(BaseModel):
    status: str = "ok"

router = APIRouter(tags=["Health"])

@router.get("/health", response_model=HealthOut)
async def health():
    return HealthOut()