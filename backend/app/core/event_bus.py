"""
In-Process Event Bus (Pub/Sub)
ระบบการส่งข้อความภายในแบบ Publish/Subscribe สำหรับสื่อสารระหว่าง Component

หน้าที่หลัก:
- ให้ Component ต่างๆ สื่อสารกันแบบ Loosely Coupled (ไม่ต้องรู้จักกัน)
- FaultDetector ตรวจพบข้อผิดพลาด → emit event → ChatOpsService รับแล้วส่ง Slack
- รองรับทั้ง sync และ async handler
- มีระบบ Wildcard ("*") เพื่อรับทุก event

ตัวอย่างการใช้งาน:
    # Publisher
    await event_bus.emit("device.fault", {"device_id": "CSR1", "type": "link_down"})

    # Subscriber
    event_bus.on("device.fault", my_handler_function)
"""

import asyncio
from typing import Any, Callable, Coroutine, Dict, List
from datetime import datetime
from app.core.logging import logger


class Event:
    """Encapsulates an event with type, payload, and metadata."""

    def __init__(self, event_type: str, data: Dict[str, Any]):
        self.event_type = event_type
        self.data = data
        self.timestamp = datetime.utcnow().isoformat()
        self.id = f"{event_type}:{self.timestamp}"

    def __repr__(self):
        return f"<Event {self.event_type} @ {self.timestamp}>"


class EventBus:
    """
    Lightweight in-process async event bus.
    Listeners are fire-and-forget — one slow handler won't block others.
    """

    def __init__(self):
        self._listeners: Dict[str, List[Callable[..., Coroutine]]] = {}
        self._history: List[Event] = []
        self._max_history = 200  # keep last N events for debugging

    # ── decorator-style subscription ────────────────────────────
    def on(self, event_type: str):
        """Decorator to register an async handler for an event type."""
        def decorator(fn: Callable[..., Coroutine]):
            self.subscribe(event_type, fn)
            return fn
        return decorator

    # ── programmatic subscription ────────────────────────────────
    def subscribe(self, event_type: str, handler: Callable[..., Coroutine]):
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(handler)
        logger.debug(f"[EventBus] Handler '{handler.__name__}' subscribed to '{event_type}'")

    # ── fire event ───────────────────────────────────────────────
    async def emit(self, event_type: str, data: Dict[str, Any] | None = None):
        """Emit an event. All matching handlers run concurrently."""
        event = Event(event_type, data or {})

        # keep recent history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        handlers = self._listeners.get(event_type, [])
        if not handlers:
            logger.debug(f"[EventBus] No handlers for '{event_type}'")
            return

        logger.info(f"[EventBus] Emitting '{event_type}' → {len(handlers)} handler(s)")

        # Fire-and-forget: create tasks so one failure doesn't stop others
        tasks = []
        for handler in handlers:
            tasks.append(asyncio.create_task(self._safe_call(handler, event)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_call(self, handler: Callable, event: Event):
        """Call handler and swallow exceptions so other handlers are not affected."""
        try:
            await handler(event)
        except Exception as exc:
            logger.error(
                f"[EventBus] Handler '{handler.__name__}' failed on "
                f"'{event.event_type}': {exc}"
            )

    # ── introspection ────────────────────────────────────────────
    @property
    def recent_events(self) -> List[Dict]:
        """Return recent event history (for debugging / API)."""
        return [
            {"event_type": e.event_type, "data": e.data, "timestamp": e.timestamp}
            for e in self._history[-50:]
        ]

    @property
    def registered_handlers(self) -> Dict[str, List[str]]:
        return {
            et: [h.__name__ for h in handlers]
            for et, handlers in self._listeners.items()
        }


# ── Singleton ────────────────────────────────────────────────────
event_bus = EventBus()
