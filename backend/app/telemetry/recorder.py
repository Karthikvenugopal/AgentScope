"""Concurrency-safe trace sequencing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from app.telemetry.events import AnyTraceEvent, BaseTraceEvent

EventT = TypeVar("EventT", bound=BaseTraceEvent)


class TraceRecorder:
    """Assign deterministic IDs and monotonically increasing sequence numbers."""

    def __init__(
        self,
        run_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
        observer: Callable[[AnyTraceEvent], Awaitable[None]] | None = None,
    ) -> None:
        self.run_id = run_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._events: list[AnyTraceEvent] = []
        self._lock = asyncio.Lock()
        self._observer = observer

    @property
    def events(self) -> tuple[AnyTraceEvent, ...]:
        return tuple(self._events)

    async def emit(self, event_class: type[EventT], **fields: Any) -> EventT:
        async with self._lock:
            sequence_number = len(self._events) + 1
            event = event_class(
                event_id=f"{self.run_id}:{sequence_number:06d}",
                run_id=self.run_id,
                sequence_number=sequence_number,
                timestamp=self._clock(),
                **fields,
            )
            self._events.append(cast(AnyTraceEvent, event))
            if self._observer is not None:
                await self._observer(cast(AnyTraceEvent, event))
            return event
