"""Thread-based scheduler for the pywebview shell."""

from __future__ import annotations

import threading
from typing import Any, Callable

from desktop_controller import Scheduler


class WebScheduler(Scheduler):
    def __init__(self, timer_factory: Callable[..., Any] = threading.Timer) -> None:
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._handles: set[Any] = set()
        self._closed = False

    def call_later(self, delay_ms: int, callback: Callable[[], None]) -> Any:
        if delay_ms < 0:
            raise ValueError("delay_ms must not be negative")
        holder: dict[str, Any] = {}

        def invoke() -> None:
            handle = holder["handle"]
            with self._lock:
                self._handles.discard(handle)
                if self._closed:
                    return
            callback()

        with self._lock:
            if self._closed:
                raise RuntimeError("scheduler is shut down")
            handle = self._timer_factory(delay_ms / 1000, invoke)
            holder["handle"] = handle
            self._handles.add(handle)
            handle.daemon = True
            handle.start()
            return handle

    def cancel(self, handle: Any) -> None:
        with self._lock:
            self._handles.discard(handle)
        handle.cancel()

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            handles = list(self._handles)
            self._handles.clear()
        for handle in handles:
            handle.cancel()
