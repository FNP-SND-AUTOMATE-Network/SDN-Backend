import time
from typing import Dict, Any, Tuple

class TTLCache:
    """
    A simple thread-safe-ish In-Memory Time-To-Live Cache.
    Useful for caching expensive API calls across users for a short duration.
    """
    def __init__(self, ttl_seconds: int = 60):
        self.ttl = ttl_seconds
        self.cache: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        if key in self.cache:
            timestamp, value = self.cache[key]
            if time.time() - timestamp <= self.ttl:
                return value
            else:
                # Expired
                del self.cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        self.cache[key] = (time.time(), value)

    def invalidate(self, key: str) -> None:
        if key in self.cache:
            del self.cache[key]

# Global instances for use across the application
live_config_cache = TTLCache(ttl_seconds=60)  # Default 60s TTL for Live Config
