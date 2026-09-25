"""Two independent desktop workflows sharing only window chrome and preferences."""
from __future__ import annotations

import threading
from copy import deepcopy
from pathlib import Path

from desktop.runtime import apply_form_settings, get_app_dir, get_data_dir, save_settings
from desktop.web_api import WebApi, success, failure
from resource_guard import (ResourceConflict, ResourceLease, canonical_path, claim_output,
                            configured_profiles, validate_resources, workflow_resources)


SESSION_METHODS = frozenset({
    "get_initial_state", "save_settings", "choose_folder", "start_batch", "stop_process",
    "continue_manual_intervention", "cancel_auto_next", "run_auto_next_now", "list_accounts",
    "select_account", "add_account", "rename_account", "remove_account", "login_account",
    "open_output_folder", "copy_log", "export_log", "clear_log", "confirm_existing_output",
})
GLOBAL_METHODS = frozenset({"get_platform_capabilities", "set_language", "set_theme",
                            "minimize_window", "toggle_maximize_window", "close_window", "move_window"})
ACCOUNT_MUTATIONS = frozenset({"select_account", "add_account", "rename_account", "remove_account", "login_account"})


class SessionManager:
    def __init__(self, *, app_dir=None, data_dir=None, api_factory=WebApi):
        self.app_dir = Path(app_dir or get_app_dir())
        self.data_dir = Path(data_dir or get_data_dir(self.app_dir))
        self._lock = threading.RLock()
        self._closed = False
        self.sessions = {}
        for session_id, directory in (("book-1", self.data_dir), ("book-2", self.data_dir / "workflows" / "book-2")):
            api = api_factory(app_dir=self.app_dir, data_dir=directory, session_id=session_id)
            api.controller._lock = self._lock
            api._dispatch_lock = self._lock
            api._launch_validator = self._prepare_start
            self.sessions[session_id] = api
        first, second = self.sessions.values()
        if not second.settings_path.exists():
            for key in ("service", "batch_size", "auto_next_enabled", "auto_next_delay_minutes", "auto_account_fallback_enabled"):
                second.settings[key] = deepcopy(first.settings[key])
            second.settings.update(image_folder="", download_folder="", start_from="")
            second._configure_controller()
        for key in ("language", "theme"):
            second.settings[key] = first.settings[key]

    @staticmethod
    def _configured_resources(settings):
        resources = [{"kind": "profile", "path": p} for p in configured_profiles(settings)]
        for key, kind in (("image_folder", "source"), ("download_folder", "output")):
            if str(settings.get(key, "")).strip():
                resources.append({"kind": kind, "path": canonical_path(settings[key])})
        return resources

    def _validate_layout(self, session_id, settings):
        own = self._configured_resources(settings)
        validate_resources(own)
        for other_id, other in self.sessions.items():
            if other_id != session_id:
                try:
                    validate_resources(own, self._configured_resources(other.settings))
                except ResourceConflict as exc:
                    raise ResourceConflict(f"{session_id} / {other_id}: {exc}") from exc

    def _prepare_start(self, api, mode):
        if self._closed:
            raise RuntimeError("App is closing")
        if api.controller.state.running:
            raise ResourceConflict("Đợi phiên trước kết thúc / Previous run is still finishing.")
        self._validate_layout(api.session_id, api.settings)
        workflow_resources(api._public_settings(), mode)
        if mode != "login":
            # Claim the book before spawning: exporting a startup log must not
            # make a fresh folder appear to contain unclaimed legacy results.
            resources = [r for r in workflow_resources(api._public_settings(), mode) if r["kind"] != "profile"]
            with ResourceLease(resources):
                claim_output(api.settings)

    def _invoke(self, method, args=(), session_id=None):
        if method not in SESSION_METHODS | GLOBAL_METHODS:
            return failure("Unsupported command")
        if session_id is not None and (not isinstance(session_id, str) or session_id not in self.sessions):
            return failure("Unknown workflow session")
        api = self.sessions[session_id or "book-1"]
        # A native dialog may remain open for minutes. It must not stop the
        # second worker's event draining or timer callbacks.
        if method == "choose_folder":
            return api.choose_folder(*args)
        if method in {"minimize_window", "toggle_maximize_window", "close_window", "move_window"}:
            return getattr(self.sessions["book-1"], method)(*args)
        with self._lock:
            if self._closed:
                return failure("App is closing")
            try:
                if method == "get_initial_state":
                    api._dispatch_once()
                    if session_id is not None:
                        return api.get_initial_state()
                    for item in self.sessions.values():
                        item._dispatch_once()
                    data = api.get_initial_state()["data"]
                    data["sessions"] = {key: item.get_initial_state()["data"] for key, item in self.sessions.items()}
                    data["active_session_id"] = "book-1"
                    return success(data)
                if method in {"set_theme", "set_language"}:
                    key = "theme" if method == "set_theme" else "language"
                    for item in self.sessions.values():
                        apply_form_settings(item.settings, {key: args[0]}, item.data_dir)
                    for item in self.sessions.values():
                        item.settings[key] = args[0]
                        save_settings(item.settings_path, item.settings)
                        item._push_event("preferences_changed", {key: args[0]})
                    return success({"settings": api._public_settings()})
                if method == "save_settings":
                    proposed = apply_form_settings(api.settings, args[0], api.data_dir)
                    # Preferences are window-wide; form saves do not revert a
                    # newer preference selected while this request was pending.
                    for key in ("theme", "language"):
                        proposed[key] = self.sessions["book-1"].settings[key]
                    if api.controller.is_running() or api.controller.state.running:
                        if proposed != api.settings:
                            raise ResourceConflict("Dừng tab này trước khi đổi cấu hình / Stop this tab before editing settings.")
                    self._validate_layout(api.session_id, proposed)
                    payload = dict(args[0], theme=proposed["theme"], language=proposed["language"])
                    return api.save_settings(payload)
                if method in ACCOUNT_MUTATIONS:
                    # Drain a completed worker before mutating its account list.
                    api._dispatch_once()
                    if api.controller.state.running:
                        raise ResourceConflict("Đợi phiên kết thúc / Wait for this run to finish.")
                if method == "start_batch":
                    api._dispatch_once()
                if method == "confirm_existing_output":
                    if api.controller.is_running() or api.controller.state.auto_next_active:
                        raise ResourceConflict("Dừng tab trước khi xác nhận / Stop this tab first.")
                    self._validate_layout(api.session_id, api.settings)
                    resources = [r for r in workflow_resources(api._public_settings()) if r["kind"] != "profile"]
                    with ResourceLease(resources):
                        claim_output(api.settings, allow_legacy=True)
                    return success({"confirmed": True})
                if method == "export_log":
                    self._validate_layout(api.session_id, api.settings)
                    resources = [{"kind": "output", "path": canonical_path(api.settings.get("download_folder"))}]
                    process = api.controller.process
                    shared_pid = process.pid if api.controller.is_running() else None
                    with ResourceLease(resources, shared_output_pid=shared_pid):
                        return api.export_log()
                return getattr(api, method)(*args)
            except Exception as exc:
                return failure(exc)

    def _attach_window(self, window):
        for api in self.sessions.values():
            api._attach_window(window)

    def _set_renderer(self, renderer):
        for api in self.sessions.values():
            api._set_renderer(renderer)

    def _start_dispatcher(self):
        for api in self.sessions.values():
            api._start_dispatcher()

    def _confirm_close(self):
        with self._lock:
            active = any(api.controller.state.running or api.controller.state.auto_next_active for api in self.sessions.values())
            api = self.sessions["book-1"]
        if not active:
            return True
        return api.window.create_confirmation_dialog(api._text("app_title"), api._text("close_active_workflows"))

    def _shutdown(self):
        with self._lock:
            self._closed = True
            for api in self.sessions.values():
                api._shutdown()
