"""In-process pub/sub for run lifecycle events, fanned out to WebSocket clients."""

import asyncio
import logging

logger = logging.getLogger(__name__)


class RunEventHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        """Non-blocking broadcast; drops events for any saturated subscriber."""
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("dropping event for saturated subscriber")
