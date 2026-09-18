"""Narrow pywebview bridge backed by the shared DesktopController."""

from __future__ import annotations

import ctypes
import json
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from desktop_controller import ControllerEvent, DesktopController
from desktop.runtime import (
    apply_form_settings,
    build_process_launch,
    get_active_chatgpt_account,
    get_app_dir,
    get_data_dir,
    load_settings,
    make_default_settings,
    normalize_chatgpt_accounts,
    save_settings as write_settings,
)
from desktop.web_scheduler import WebScheduler
from desktop.web_text import WEB_TEXT


VALID_MODES = {"main", "retry", "force"}
VALID_FOLDER_KINDS = {"source", "output", "profile"}
RUN_CONFIGURATION_KEYS = {
    "image_folder",
    "download_folder",
    "profile_dir",
    "batch_size",
    "start_from",
    "auto_next_enabled",
    "auto_next_delay_minutes",
    "auto_account_fallback_enabled",
    "service",
}


def success(data: Any = None) -> dict[str, Any]:
    return {"ok": True, "data": {} if data is None else data}


def failure(error: Exception | str) -> dict[str, Any]:
    return {"ok": False, "error": str(error)}


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)


class WebApi:
    """Whitelisted facade; no command, environment, or controller object is exposed."""

    def __init__(
        self,
        *,
        controller: DesktopController | None = None,
        scheduler: WebScheduler | None = None,
        app_dir: Path | None = None,
        settings_path: Path | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.app_dir = Path(app_dir or get_app_dir())
        self.data_dir = Path(data_dir or get_data_dir(self.app_dir))
        self.settings_path = Path(settings_path or (self.data_dir / "app_settings.json"))
        self.defaults = make_default_settings(self.data_dir)
        self.settings = load_settings(self.settings_path, self.defaults)
        normalize_chatgpt_accounts(self.settings, self.data_dir)
        self.scheduler = scheduler or WebScheduler()
        self.controller = controller or DesktopController(self.scheduler)
        self.window: Any | None = None
        self.renderer = "initializing"
        self.status = {"key": "ready", "params": {}}
        self.sequence = 0
        self.sent_events: list[dict[str, Any]] = []
        self._event_lock = threading.Lock()
        self._dispatch_lock = threading.Lock()
        self._stop_dispatcher = threading.Event()
        self._dispatcher: threading.Thread | None = None
        self._closed = False
        self._configure_controller()

    def _attach_window(self, window: Any) -> None:
        self.window = window

    def _set_renderer(self, renderer: Any) -> None:
        self.renderer = str(renderer or "unknown")

    def _start_dispatcher(self) -> None:
        if self._dispatcher and self._dispatcher.is_alive():
            return
        self._stop_dispatcher.clear()
        self._dispatcher = threading.Thread(target=self._dispatch_loop, daemon=True, name="web-controller-events")
        self._dispatcher.start()

    def _dispatch_loop(self) -> None:
        while not self._stop_dispatcher.wait(0.1):
            self._dispatch_once()

    def _dispatch_once(self) -> list[dict[str, Any]]:
        delivered: list[dict[str, Any]] = []
        with self._dispatch_lock:
            while True:
                events = self.controller.drain_events()
                if not events:
                    break
                for event in events:
                    delivered.append(self._push_event(event.type, event.data))
                    try:
                        self._adapt_controller_event(event)
                    except Exception as exc:
                        delivered.append(self._push_event(
                            "bridge_error",
                            {"source_event": event.type, "error": str(exc)},
                        ))
        return delivered

    def _push_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._event_lock:
            self.sequence += 1
            message = {"sequence": self.sequence, "type": event_type, "payload": json_safe(payload)}
            self.sent_events.append(message)
        if self.window is not None and not self._closed:
            encoded = json.dumps(message, ensure_ascii=False).replace("</", "<\\/")
            try:
                self.window.run_js(f"window.batchTranslatorReceive({encoded});")
            except Exception:
                # A closing or temporarily unavailable webview must not stop
                # controller draining or the auto-next state machine.
                pass
        return message

    def _adapt_controller_event(self, event: ControllerEvent) -> None:
        kind, data = event.type, event.data
        if kind == "process_started":
            self._set_status("status_running")
            self._append_log(f"\n=== {data['mode'].upper()} ===\n")
        elif kind == "manual_action_required":
            self._set_status("manual_wait")
        elif kind == "continue_sent":
            self._set_status("continue_sent")
            self._append_log("\n=== CONTINUE ===\n")
        elif kind == "stopped":
            self._set_status("stopped")
            self._append_log("\n=== STOPPED ===\n")
        elif kind == "no_process":
            self._set_status("no_process")
        elif kind == "batch_result":
            result = data["result"]
            self._append_log("\n" + self._text(
                "batch_result_log",
                success=result.get("success_count", 0),
                selected=result.get("selected_count", 0),
                failed=result.get("failure_count", 0),
            ) + "\n")
        elif kind == "account_event":
            account_event = data["event"]
            if account_event.get("event") == "account_switched":
                self._select_worker_account(account_event.get("account_id"))
            self._render_account_event(account_event)
        elif kind == "auto_next_tick":
            remaining = int(data["remaining"])
            self._set_status("auto_countdown", time=f"{remaining // 60:02d}:{remaining % 60:02d}")
        elif kind == "auto_next_cancelled" and data.get("active") and data.get("announce"):
            self._set_status("auto_cancelled")
        elif kind == "auto_next_start_requested":
            if not self._closed:
                self._start("main", auto_started=True)
        elif kind == "auto_next_recovered":
            self._append_log("\n" + self._text("auto_next_recovered", code=data["code"]) + "\n")
        elif kind == "auto_next_skipped":
            self._append_log("\n" + self._text(data["reason"], **data["values"]) + "\n")
        elif kind in {"reader_error", "continue_error"}:
            self._set_status("error_detail", error=data.get("error", ""))
        elif kind == "invalid_auto_next_delay":
            self._set_status("invalid_auto_next_delay")
        elif kind == "process_outcome":
            self._render_process_outcome(data)

    def _text(self, key: str, **params: Any) -> str:
        language = self.settings.get("language", "vi")
        value = WEB_TEXT.get(language, WEB_TEXT["vi"]).get(key, WEB_TEXT["vi"].get(key, key))
        try:
            return value.format(**params)
        except (KeyError, ValueError):
            return value

    def _render_account_event(self, event: dict[str, Any]) -> None:
        event_name = event.get("event")
        mapping = {
            "account_quota_exhausted": ("account_quota_log", {"name": event.get("account_name", "ChatGPT")}),
            "account_switched": ("account_switched_log", {
                "name": event.get("account_name", "ChatGPT"), "image": event.get("image", ""),
            }),
            "account_skipped": ("account_skipped_log", {
                "name": event.get("account_name", "ChatGPT"), "reason": event.get("reason", ""),
            }),
            "job_waiting": ("account_waiting_log", {
                "reason": event.get("reason", ""), "image": event.get("image", ""),
            }),
        }
        entry = mapping.get(event_name)
        if entry:
            key, params = entry
            self._append_log("\n" + self._text(key, **params) + "\n")
        if event_name == "job_waiting":
            self._set_status("account_waiting_status")

    def _render_process_outcome(self, data: dict[str, Any]) -> None:
        outcome = data.get("outcome")
        exit_code = data.get("exit_code", "")
        job = data.get("job") or {}
        if outcome == "login":
            self._set_status("login_ready" if exit_code == 0 else "process_done")
        elif outcome == "complete":
            self._set_status("complete_outcome", done=job.get("done", 0), total=job.get("total", 0))
        elif outcome == "waiting_quota":
            self._set_status(
                "waiting_quota_outcome",
                reason=job.get("waiting_reason", ""),
                image=job.get("waiting_image", ""),
            )
        elif outcome == "needs_retry":
            self._set_status("needs_retry_outcome", failed=job.get("failed", 0))
        else:
            self._set_status("process_done")

    def _set_status(self, key: str, **params: Any) -> None:
        self.status = {"key": key, "params": params}
        self._push_event("status_changed", self.status)

    def _append_log(self, text: str) -> None:
        self.controller.append_log(text)

    def _configure_controller(self) -> None:
        try:
            delay = DesktopController.parse_auto_next_delay(str(self.settings.get("auto_next_delay_minutes", "2")))
        except (TypeError, ValueError):
            delay = None
        self.controller.configure_auto_next(bool(self.settings.get("auto_next_enabled", False)), delay)

    def _snapshot(self) -> dict[str, Any]:
        state = asdict(self.controller.state)
        state["status"] = dict(self.status)
        state["log_history"] = "".join(self.controller.log_history)
        state["sequence"] = self.sequence
        return json_safe(state)

    def _public_settings(self) -> dict[str, Any]:
        data = dict(self.settings)
        data["chatgpt_accounts"] = [dict(account) for account in normalize_chatgpt_accounts(data, self.data_dir)]
        if data.get("service") == "chatgpt":
            data["profile_dir"] = get_active_chatgpt_account(data, self.data_dir)["profile_dir"]
        else:
            data["profile_dir"] = data["gemini_profile_dir"]
        return json_safe(data)

    def get_initial_state(self) -> dict[str, Any]:
        try:
            return success({
                "settings": self._public_settings(),
                "controller": self._snapshot(),
                "localization": WEB_TEXT,
                "capabilities": self.get_platform_capabilities()["data"],
            })
        except Exception as exc:
            return failure(exc)

    def get_platform_capabilities(self) -> dict[str, Any]:
        return success({
            "platform": "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux"),
            "webview_backend": self.renderer,
            "supports_vibrancy": sys.platform == "darwin",
            "supports_native_folder_dialog": True,
            "frozen": bool(getattr(sys, "frozen", False)),
            "python": platform.python_version(),
        })

    def save_settings(self, payload: Any) -> dict[str, Any]:
        try:
            previous = self.settings
            updated = apply_form_settings(previous, payload, self.data_dir)
            settings_changed = updated != previous
            run_configuration_changed = any(
                updated.get(key) != previous.get(key)
                for key in RUN_CONFIGURATION_KEYS
            )
            self.settings = updated
            if settings_changed:
                write_settings(self.settings_path, self.settings)
            if run_configuration_changed:
                self.controller.mark_run_configuration_changed()
            self._configure_controller()
            self._dispatch_once()
            return success({"settings": self._public_settings()})
        except Exception as exc:
            return failure(exc)

    def choose_folder(self, kind: Any) -> dict[str, Any]:
        try:
            if kind not in VALID_FOLDER_KINDS:
                raise ValueError("folder kind must be source, output, or profile")
            if self.window is None:
                raise RuntimeError("window is not ready")
            import webview

            selected = self.window.create_file_dialog(webview.FileDialog.FOLDER)
            path = selected[0] if selected else None
            return success({"kind": kind, "path": path, "cancelled": path is None})
        except Exception as exc:
            return failure(exc)

    def start_batch(self, mode: Any) -> dict[str, Any]:
        try:
            if mode not in VALID_MODES:
                raise ValueError("mode must be main, retry, or force")
            self._start(mode)
            self._dispatch_once()
            return success({"state": self._snapshot()})
        except Exception as exc:
            return failure(exc)

    def _start(self, mode: str, *, auto_started: bool = False) -> None:
        if self.controller.is_running():
            raise RuntimeError("a batch is already running")
        if mode == "force" and not str(self.settings.get("start_from", "")).strip():
            raise ValueError("start_from is required for force mode")
        if mode != "login":
            try:
                if int(str(self.settings.get("batch_size", "")).strip()) < 1:
                    raise ValueError
            except ValueError as exc:
                raise ValueError("batch_size must be a positive integer") from exc
        if mode == "main" and self.settings.get("auto_next_enabled"):
            DesktopController.parse_auto_next_delay(str(self.settings.get("auto_next_delay_minutes", "")))
        if mode == "login" and self.settings.get("service") != "chatgpt":
            raise ValueError("login is available only for ChatGPT accounts")
        script = self.app_dir / "run_chatgpt_batch.py"
        if not getattr(sys, "frozen", False) and not script.is_file():
            raise FileNotFoundError(f"worker not found: {script}")
        write_settings(self.settings_path, self.settings)
        self._configure_controller()
        launch = build_process_launch(self.settings, mode, app_dir=self.app_dir)
        if not self.controller.start(mode, launch, auto_started=auto_started):
            raise RuntimeError("a batch is already running")

    def stop_process(self) -> dict[str, Any]:
        try:
            stopped = self.controller.stop()
            self._dispatch_once()
            return success({"stopped": stopped, "state": self._snapshot()})
        except Exception as exc:
            return failure(exc)

    def continue_manual_intervention(self) -> dict[str, Any]:
        try:
            continued = self.controller.send_continue()
            self._dispatch_once()
            if not continued:
                raise RuntimeError("no running process accepted continue")
            return success({"continued": True, "state": self._snapshot()})
        except Exception as exc:
            return failure(exc)

    def cancel_auto_next(self) -> dict[str, Any]:
        try:
            active = self.controller.cancel_auto_next(announce=True)
            self._dispatch_once()
            return success({"cancelled": active, "state": self._snapshot()})
        except Exception as exc:
            return failure(exc)

    def run_auto_next_now(self) -> dict[str, Any]:
        try:
            started = self.controller.run_auto_next_now()
            self._dispatch_once()
            if not started:
                raise RuntimeError("no automatic run is scheduled")
            return success({"started": True, "state": self._snapshot()})
        except Exception as exc:
            return failure(exc)

    def list_accounts(self) -> dict[str, Any]:
        return success({
            "accounts": [dict(account) for account in normalize_chatgpt_accounts(self.settings, self.data_dir)],
            "active_id": self.settings["active_chatgpt_account_id"],
        })

    def select_account(self, account_id: Any) -> dict[str, Any]:
        try:
            self._require_idle()
            account = self._find_account(account_id)
            self.settings["active_chatgpt_account_id"] = account["id"]
            self.settings["profile_dir"] = account["profile_dir"]
            self._settings_changed()
            return self.list_accounts()
        except Exception as exc:
            return failure(exc)

    def add_account(self, name: Any) -> dict[str, Any]:
        try:
            self._require_idle()
            name = self._validate_account_name(name)
            accounts = normalize_chatgpt_accounts(self.settings, self.data_dir)
            if any(item["name"].casefold() == name.casefold() for item in accounts):
                raise ValueError("account name already exists")
            safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("._-") or "account"
            base = self.data_dir / f"chatgpt_auto_profile_{safe_name[:48]}"
            existing = {item["profile_dir"] for item in accounts}
            candidate, suffix = base, 2
            while str(candidate) in existing or candidate.exists():
                candidate = self.data_dir / f"{base.name}_{suffix}"
                suffix += 1
            account = {"id": f"account-{uuid.uuid4().hex}", "name": name, "profile_dir": str(candidate)}
            accounts.append(account)
            self.settings["active_chatgpt_account_id"] = account["id"]
            self.settings["profile_dir"] = account["profile_dir"]
            self._settings_changed()
            return self.list_accounts()
        except Exception as exc:
            return failure(exc)

    def rename_account(self, account_id: Any, name: Any) -> dict[str, Any]:
        try:
            self._require_idle()
            account = self._find_account(account_id)
            name = self._validate_account_name(name)
            if any(item["id"] != account["id"] and item["name"].casefold() == name.casefold() for item in self.settings["chatgpt_accounts"]):
                raise ValueError("account name already exists")
            account["name"] = name
            self._settings_changed()
            return self.list_accounts()
        except Exception as exc:
            return failure(exc)

    def remove_account(self, account_id: Any) -> dict[str, Any]:
        try:
            self._require_idle()
            accounts = normalize_chatgpt_accounts(self.settings, self.data_dir)
            if len(accounts) < 2:
                raise ValueError("at least one ChatGPT account is required")
            account = next((item for item in accounts if item["id"] == account_id), None)
            if account is None:
                raise ValueError("unknown account")
            remaining = [item for item in accounts if item["id"] != account_id]
            self.settings["chatgpt_accounts"] = remaining
            active_id = self.settings.get("active_chatgpt_account_id")
            if active_id == account_id or not any(item["id"] == active_id for item in remaining):
                active_id = remaining[0]["id"]
            self.settings["active_chatgpt_account_id"] = active_id
            active = next(item for item in remaining if item["id"] == active_id)
            self.settings["profile_dir"] = active["profile_dir"]
            self._settings_changed()
            return self.list_accounts()
        except Exception as exc:
            return failure(exc)

    def login_account(self, account_id: Any) -> dict[str, Any]:
        selected = self.select_account(account_id)
        if not selected.get("ok"):
            return selected
        try:
            self.settings["service"] = "chatgpt"
            self._start("login")
            self._dispatch_once()
            return success({"state": self._snapshot()})
        except Exception as exc:
            return failure(exc)

    def _find_account(self, account_id: Any) -> dict[str, str]:
        if not isinstance(account_id, str):
            raise ValueError("account id must be a string")
        account = next((item for item in normalize_chatgpt_accounts(self.settings, self.data_dir) if item["id"] == account_id), None)
        if account is None:
            raise ValueError("unknown account")
        return account

    @staticmethod
    def _validate_account_name(name: Any) -> str:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise ValueError("invalid account name")
        return name.strip()

    def _require_idle(self) -> None:
        if self.controller.is_running():
            raise RuntimeError("stop the current batch before changing accounts")

    def _settings_changed(self) -> None:
        write_settings(self.settings_path, self.settings)
        self.controller.mark_run_configuration_changed()
        self._configure_controller()
        self._dispatch_once()

    def _select_worker_account(self, account_id: Any) -> None:
        try:
            account = self._find_account(account_id)
        except ValueError:
            return
        self.settings["active_chatgpt_account_id"] = account["id"]
        self.settings["profile_dir"] = account["profile_dir"]
        write_settings(self.settings_path, self.settings)

    def set_language(self, code: Any) -> dict[str, Any]:
        return self.save_settings({"language": code})

    def set_theme(self, code: Any) -> dict[str, Any]:
        return self.save_settings({"theme": code})

    def minimize_window(self) -> dict[str, Any]:
        """Minimize the host pywebview window. Used by the Mac-style traffic light."""
        try:
            if self.window is None:
                raise RuntimeError("window is not attached")
            self.window.minimize()
            return success({"minimized": True})
        except Exception as exc:
            return failure(exc)

    def toggle_maximize_window(self) -> dict[str, Any]:
        """Toggle between maximized and the previous restored state. Mac-style zoom button."""
        try:
            if self.window is None:
                raise RuntimeError("window is not attached")
            is_max = False
            native = getattr(self.window, "native", None)
            if native is not None and hasattr(native, "WindowState"):
                is_max = str(native.WindowState).lower() == "maximized"
            elif hasattr(self, "_is_zoomed"):
                is_max = bool(self._is_zoomed)

            if not is_max:
                try:
                    self._pre_zoom_state = {
                        "x": int(self.window.x),
                        "y": int(self.window.y),
                        "width": int(self.window.width),
                        "height": int(self.window.height),
                    }
                except Exception:
                    self._pre_zoom_state = None
                self.window.maximize()
                self._is_zoomed = True
            else:
                self.window.restore()
                pre = getattr(self, "_pre_zoom_state", None)
                if pre is not None:
                    try:
                        self.window.move(pre["x"], pre["y"])
                        self.window.resize(pre["width"], pre["height"])
                    except Exception:
                        pass
                self._is_zoomed = False
            return success({"maximized": self._is_zoomed})
        except Exception as exc:
            return failure(exc)

    def close_window(self) -> dict[str, Any]:
        """Close the host pywebview window. Mac-style traffic light."""
        try:
            if self.window is None:
                raise RuntimeError("window is not attached")
            if hasattr(self.window, "destroy") and callable(self.window.destroy):
                self.window.destroy()
            elif hasattr(self.window, "close") and callable(self.window.close):
                self.window.close()
            else:
                raise AttributeError("Window has neither destroy nor close method")
            return success({"closed": True})
        except Exception as exc:
            return failure(exc)

    def open_output_folder(self) -> dict[str, Any]:
        try:
            folder = Path(str(self.settings.get("download_folder", "")))
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            return success({"path": str(folder)})
        except Exception as exc:
            return failure(exc)

    def copy_log(self) -> dict[str, Any]:
        try:
            text = "".join(self.controller.log_history)
            if not text.strip():
                raise ValueError("log is empty")
            self._copy_text(text)
            return success({"characters": len(text)})
        except Exception as exc:
            return failure(exc)

    @staticmethod
    def _copy_text(text: str) -> None:
        if os.name == "nt":
            WebApi._copy_windows_text(text)
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)

    @staticmethod
    def _copy_windows_text(text: str) -> None:
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
        kernel32.GlobalFree.restype = wintypes.HANDLE
        memory = None
        for _ in range(10):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            raise OSError("could not open clipboard")
        try:
            user32.EmptyClipboard()
            encoded = (text + "\0").encode("utf-16-le")
            memory = kernel32.GlobalAlloc(0x0002, len(encoded))
            pointer = kernel32.GlobalLock(memory)
            ctypes.memmove(pointer, encoded, len(encoded))
            kernel32.GlobalUnlock(memory)
            if not user32.SetClipboardData(13, memory):
                raise OSError("could not set clipboard data")
            memory = None
        finally:
            if memory:
                kernel32.GlobalFree(memory)
            user32.CloseClipboard()

    def export_log(self) -> dict[str, Any]:
        try:
            text = "".join(self.controller.log_history)
            if not text.strip():
                raise ValueError("log is empty")
            path = Path(str(self.settings.get("download_folder", ""))) / "process_log.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return success({"path": str(path)})
        except Exception as exc:
            return failure(exc)

    def clear_log(self) -> dict[str, Any]:
        try:
            self.controller.clear_log()
            self._dispatch_once()
            return success({"cleared": True})
        except Exception as exc:
            return failure(exc)

    def _shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_dispatcher.set()
        with self._dispatch_lock:
            self.controller.shutdown()
            self.scheduler.shutdown()
