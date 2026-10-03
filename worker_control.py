"""Cooperative cancellation without calling browser APIs across threads."""

from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path

STOP_FILE_ENV = "BATCH_TRANSLATOR_STOP_FILE"
POLL_SECONDS = 0.2


class WorkerStopRequested(BaseException):
    """Unwind browser finalizers without treating cancellation as an image error."""


def check_stop_requested() -> None:
    stop_file = os.environ.get(STOP_FILE_ENV, "")
    if stop_file and Path(stop_file).exists():
        raise WorkerStopRequested()


def cooperative_sleep(seconds: float) -> None:
    """Keep ordinary CLI sleep behavior, but respond promptly to desktop Stop."""
    check_stop_requested()
    if not os.environ.get(STOP_FILE_ENV):
        time.sleep(seconds)
        return
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        check_stop_requested()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(POLL_SECONDS, remaining))


def wait_for_continue(prompt: str) -> str:
    """Wait for one ENTER while letting the owning thread close its browser."""
    check_stop_requested()
    if not os.environ.get(STOP_FILE_ENV):
        return input(prompt)
    result: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def read_input() -> None:
        try:
            result.put((True, input(prompt)))
        except BaseException as exc:
            result.put((False, exc))

    # Only stdin is read here. Playwright and cleanup stay on the main thread.
    # A blocked reader must not prevent process exit on Stop.
    threading.Thread(target=read_input, daemon=True).start()
    while True:
        check_stop_requested()
        try:
            ok, value = result.get(timeout=POLL_SECONDS)
        except queue.Empty:
            continue
        check_stop_requested()
        if not ok:
            raise value
        return str(value)
