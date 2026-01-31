from fastapi import APIRouter
from app.schemas.intent import IntentRequest, IntentResponse
from app.services.intent_service import IntentService

# ไม่มี prefix ที่นี่ เพื่อให้ nbi.py เป็นคนกำหนด namespace
router = APIRouter(tags=["NBI"])

_service = IntentService()


@router.post("/intent", response_model=IntentResponse)
async def handle_intent(req: IntentRequest) -> IntentResponse:
    """
    Intent-Based Hybrid NBI Endpoint
    Flow: Validate -> DeviceProfile -> StrategyResolver -> Driver -> ODL -> Normalize -> Response
    """
    return await _service.handle(req)
