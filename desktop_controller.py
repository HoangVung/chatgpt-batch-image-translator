"""UI-independent process controller for the desktop application."""

from __future__ import annotations

import json
import math
import os
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable


BATCH_RESULT_PREFIX = "__BATCH_RESULT__="
ACCOUNT_EVENT_PREFIX = "__ACCOUNT_EVENT__="


class Scheduler:
    """Minimal timer interface used by auto-next."""

    def call_later(self, delay_ms: int, callback: Callable[[], None]) -> Any:
        raise NotImplementedError

    def cancel(self, handle: Any) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class ProcessLaunch:
    command: list[str]
    cwd: str
    env: dict[str, str]
    creationflags: int = 0


@dataclass
class DesktopState:
    running: bool = False
    progress_done: int = 0
    progress_total: int = 0
    manual_action_required: bool = False
    current_run_mode: str | None = None
    current_run_intervened: bool = False
    current_batch_result: dict[str, Any] | None = None
    auto_next_enabled: bool = False
    auto_next_delay_seconds: int | None = None
    auto_next_active: bool = False
    auto_next_deadline: float | None = None
    auto_next_token: int = 0


@dataclass(frozen=True)
class ControllerEvent:
    type: str
    data: dict[str, Any]


class DesktopController:
    """Own worker lifecycle, protocol parsing, process state, and auto-next."""

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        thread_factory: Callable[..., Any] = threading.Thread,
        monotonic: Callable[[], float] = time.monotonic,
        process_tree_terminator: Callable[[Any], None] | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.state = DesktopState()
        self.process: Any | None = None
        self.log_history: list[str] = []
        self._popen_factory = popen_factory
        self._thread_factory = thread_factory
        self._monotonic = monotonic
        self._process_tree_terminator = process_tree_terminator or self._terminate_process_tree
        self._reader_queue: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self._events: deque[ControllerEvent] = deque()
        self._auto_next_handle: Any | None = None

    @staticmethod
    def parse_auto_next_delay(value: str) -> int:
        minutes = float(value.strip())
        if not math.isfinite(minutes) or minutes <= 0:
            raise ValueError
        return max(1, round(minutes * 60))

    def configure_auto_next(self, enabled: bool, delay_seconds: int | None) -> None:
        self.state.auto_next_enabled = bool(enabled)
        self.state.auto_next_delay_seconds = delay_seconds

    def is_running(self) -> bool:
        process = self.process
        if process is None:
            return False
        try:
            return process.poll() is None
        except AttributeError:
            return True

    def start(self, mode: str, launch: ProcessLaunch, *, auto_started: bool = False) -> bool:
        if self.is_running():
            return False

        if not auto_started:
            self.cancel_auto_next()

        process = self._popen_factory(
            launch.command,
            cwd=launch.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=launch.env,
            bufsize=1,
            creationflags=launch.creationflags,
        )

        self.process = process
        self.state.running = True
        self.state.progress_done = 0
        self.state.progress_total = 0
        self.state.manual_action_required = False
        self.state.current_run_mode = mode
        self.state.current_run_intervened = False
        self.state.current_batch_result = None
        self._emit("progress_changed", done=0, total=0)
        self._emit("process_started", mode=mode)

        reader = self._thread_factory(
            target=self.read_process_output,
            args=(process,),
            daemon=True,
        )
        reader.start()
        return True

    def read_process_output(self, process: Any) -> None:
        try:
            for line in process.stdout:
                self._reader_queue.put(("line", line))
        except Exception as exc:
            self._reader_queue.put(("reader_error", str(exc)))
        finally:
            code = process.wait()
            self._reader_queue.put(("line", f"\n=== KẾT THÚC, EXIT CODE: {code} ===\n"))
            self._reader_queue.put(("done", process, code))

    def drain_events(self) -> list[ControllerEvent]:
        while True:
            try:
                item = self._reader_queue.get_nowait()
            except queue.Empty:
                break

            kind = item[0]
            if kind == "line":
                self.handle_worker_output(item[1])
            elif kind == "reader_error":
                self._emit("reader_error", error=item[1])
            elif kind == "done":
                process, exit_code = item[1], item[2]
                if process is self.process:
                    self.handle_process_done(exit_code)

        events = list(self._events)
        self._events.clear()
        return events

    def append_log(self, text: str, *, parse_worker_markers: bool = False) -> None:
        self.log_history.append(text)
        self._emit("log_appended", text=text)
        if parse_worker_markers:
            self._update_progress_from_log(text)
            self._update_manual_state_from_log(text)

    def clear_log(self) -> None:
        self.log_history.clear()
        self._emit("log_cleared")

    def handle_worker_output(self, text: str) -> None:
        if text.startswith(ACCOUNT_EVENT_PREFIX):
            try:
                event = json.loads(text[len(ACCOUNT_EVENT_PREFIX):].strip())
                if not isinstance(event, dict):
                    raise ValueError("Account event is not an object")
                self._emit("account_event", event=event)
                return
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        if text.startswith(BATCH_RESULT_PREFIX):
            try:
                result = json.loads(text[len(BATCH_RESULT_PREFIX):].strip())
                if not isinstance(result, dict):
                    raise ValueError("Batch result is not an object")
                self.state.current_batch_result = result
                self._emit("batch_result", result=result)
                return
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        self.append_log(text, parse_worker_markers=True)

    def _update_manual_state_from_log(self, text: str) -> None:
        if "MANUAL_ACTION_REQUIRED" not in text:
            return
        self.state.manual_action_required = True
        self._emit("manual_action_required")

    def _update_progress_from_log(self, text: str) -> None:
        if "📌 Batch lần này:" in text:
            try:
                self.state.progress_total = int(text.split(":")[-1].strip().split()[0])
                self.state.progress_done = 0
                self._emit(
                    "progress_changed",
                    done=self.state.progress_done,
                    total=self.state.progress_total,
                    reset=True,
                )
            except (IndexError, TypeError, ValueError):
                pass

        if "✓ DONE" in text or "✗ Lỗi:" in text:
            self.state.progress_done += 1
            self._emit(
                "progress_changed",
                done=self.state.progress_done,
                total=max(self.state.progress_total, 1),
            )

    def mark_run_configuration_changed(self) -> None:
        if self.is_running():
            self.state.current_run_intervened = True
        self.cancel_auto_next()

    def send_continue(self) -> bool:
        if not self.is_running():
            return False
        try:
            self.process.stdin.write("\n")
            self.process.stdin.flush()
        except Exception as exc:
            self._emit("continue_error", error=exc)
            return False

        self.state.current_run_intervened = True
        self.state.manual_action_required = False
        self._emit("continue_sent")
        return True

    def stop(self) -> bool:
        cancelled_auto_run = self.cancel_auto_next(announce=True)
        if self.is_running():
            self.state.current_run_intervened = True
            self._process_tree_terminator(self.process)
            self.state.manual_action_required = False
            self._emit("stopped")
            return True
        if not cancelled_auto_run:
            self._emit("no_process")
        return False

    def shutdown(self) -> None:
        self.cancel_auto_next()
        if self.is_running():
            self.stop()

    def cancel_auto_next(self, announce: bool = False) -> bool:
        active = self.state.auto_next_active or self._auto_next_handle is not None
        self.state.auto_next_token += 1
        if self._auto_next_handle is not None:
            try:
                self.scheduler.cancel(self._auto_next_handle)
            except Exception:
                pass
        self._auto_next_handle = None
        self.state.auto_next_active = False
        self.state.auto_next_deadline = None
        self._emit("auto_next_cancelled", active=active, announce=announce)
        return active

    def schedule_auto_next(self) -> bool:
        delay_seconds = self.state.auto_next_delay_seconds
        if delay_seconds is None or delay_seconds < 1:
            self._emit("invalid_auto_next_delay")
            return False

        self.cancel_auto_next()
        self.state.auto_next_token += 1
        token = self.state.auto_next_token
        self.state.auto_next_active = True
        self.state.auto_next_deadline = self._monotonic() + delay_seconds
        result = self.state.current_batch_result or {}
        self._emit(
            "auto_next_scheduled",
            count=result.get("requested_batch_size", "?"),
            seconds=delay_seconds,
        )
        self.update_auto_next_countdown(token)
        return True

    def update_auto_next_countdown(self, token: int) -> None:
        deadline = self.state.auto_next_deadline
        if token != self.state.auto_next_token or deadline is None:
            return

        remaining = max(0, int(deadline - self._monotonic() + 0.999))
        self._emit("auto_next_tick", remaining=remaining)
        if remaining > 0:
            self._auto_next_handle = self.scheduler.call_later(
                1000,
                lambda: self.update_auto_next_countdown(token),
            )
            return

        self._auto_next_handle = None
        self.state.auto_next_active = False
        self.state.auto_next_deadline = None
        if self.state.auto_next_enabled and not self.is_running():
            self._emit("auto_next_running")
            self._emit("auto_next_start_requested")

    def run_auto_next_now(self) -> bool:
        if not self.state.auto_next_active:
            return False
        self.cancel_auto_next()
        self._emit("auto_next_running")
        self._emit("auto_next_start_requested")
        return True

    def get_auto_next_skip_reason(self, exit_code: int) -> tuple[str, dict[str, Any]] | None:
        state = self.state
        if not state.auto_next_enabled or state.current_run_mode != "main":
            return None
        if state.current_run_intervened:
            return "auto_skip_intervened", {}
        result = state.current_batch_result
        if not result:
            return "auto_skip_missing_result", {}
        if result.get("job", {}).get("state") in ("complete", "needs_retry"):
            return "auto_skip_no_more", {}

        try:
            selected = int(result.get("selected_count", 0))
            requested = int(result.get("requested_batch_size", 0))
            completed = int(result.get("completed_count", 0))
            succeeded = int(result.get("success_count", 0))
            failed = int(result.get("failure_count", 0))
            next_pending = int(result.get("next_pending_count", 0))
            worker_result_code = int(result.get("exit_code", -1))
        except (TypeError, ValueError):
            return "auto_skip_missing_result", {}

        if requested < 1 or selected != requested:
            return "auto_skip_incomplete", {"count": requested}
        if completed != selected or succeeded != selected or failed:
            return "auto_skip_failed", {}
        if next_pending < 1:
            return "auto_skip_no_more", {}
        if exit_code != 0:
            if worker_result_code == 0:
                return "", {"recovered_exit_code": exit_code}
            return "auto_skip_process_error", {"code": exit_code}
        return "", {}

    def handle_process_done(self, exit_code: int) -> None:
        self.process = None
        self.state.running = False
        self.state.manual_action_required = False
        self._emit("process_completed", exit_code=exit_code)

        if self.state.current_run_mode == "login":
            self._emit("process_outcome", outcome="login", exit_code=exit_code)
            return

        job = (self.state.current_batch_result or {}).get("job", {})
        if exit_code == 0 and job.get("state") == "complete":
            self.cancel_auto_next()
            self._emit("process_outcome", outcome="complete", exit_code=exit_code, job=job)
            return
        if exit_code == 4 and job.get("state") == "waiting_quota":
            self.cancel_auto_next()
            self._emit("process_outcome", outcome="waiting_quota", exit_code=exit_code, job=job)
            return
        if exit_code == 2 and job.get("state") == "needs_retry":
            self.cancel_auto_next()
            self._emit("process_outcome", outcome="needs_retry", exit_code=exit_code, job=job)
            return

        reason, values = self.get_auto_next_skip_reason(exit_code) or (None, {})
        if reason == "":
            if "recovered_exit_code" in values:
                self._emit("auto_next_recovered", code=values["recovered_exit_code"])
            if self.schedule_auto_next():
                return
        elif reason is not None:
            self._emit("auto_next_skipped", reason=reason, values=values)

        self._emit("process_outcome", outcome="done", exit_code=exit_code, job=job)

    def _emit(self, event_type: str, **data: Any) -> None:
        self._events.append(ControllerEvent(event_type, data))

    @staticmethod
    def _terminate_process_tree(process: Any) -> None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            process.terminate()
