from abc import ABC, abstractmethod
from typing import Any, Dict
from app.schemas.device_profile import DeviceProfile
from app.schemas.request_spec import RequestSpec

class BaseDriver(ABC):
    name: str

    @abstractmethod
    def build(self, device: DeviceProfile, intent: str, params: Dict[str, Any]) -> RequestSpec:
        ...
