from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, AsyncIterator


class EventHub:
    """Fan-out event queues for per-investigation SSE consumers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, investigation_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            self._history[investigation_id].append(event)
            subscribers = tuple(self._subscribers[investigation_id])
        for queue in subscribers:
            await queue.put(event)

    async def subscribe(self, investigation_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        async with self._lock:
            history = list(self._history[investigation_id])
            self._subscribers[investigation_id].add(queue)
        try:
            for event in history:
                yield event
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._subscribers[investigation_id].discard(queue)
