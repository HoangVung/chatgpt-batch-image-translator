"""Production pywebview shell entrypoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop.web_api import WebApi
from desktop.workflow_sessions import SessionManager, WORKFLOW_IDS
from desktop.window_identity import (
    enable_windows_taskbar_minimize,
    set_windows_app_user_model_id,
)


RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
UI_ENTRYPOINT = RESOURCE_ROOT / "ui" / "index.html"
WINDOWS_ICON_FILE = RESOURCE_ROOT / "assets" / "app-icon.ico"


class WebShellStartupError(RuntimeError):
    """Raised only when the native web shell fails before initialization."""


class WebBridge:
    """Expose only the production bridge methods to pywebview.

    pywebview recursively inspects public attributes on ``js_api`` objects.
    Passing ``WebApi`` directly therefore makes it walk the attached native
    window and its .NET accessibility graph.  Keep runtime state private and
    delegate only the intentionally supported bridge contract.
    """

    __slots__ = ("_api",)

    def __init__(self, api: WebApi) -> None:
        self._api = api

    def _call(self, method, args=(), session_id=None):
        if isinstance(self._api, SessionManager):
            return self._api._invoke(method, args, session_id)
        return getattr(self._api, method)(*args)

    def get_initial_state(self, session_id=None):
        return self._call("get_initial_state", session_id=session_id)

    def get_platform_capabilities(self):
        return self._call("get_platform_capabilities")

    def save_settings(self, payload, session_id=None):
        return self._call("save_settings", (payload,), session_id)

    def choose_folder(self, kind, session_id=None):
        return self._call("choose_folder", (kind,), session_id)

    def start_batch(self, mode, session_id=None):
        return self._call("start_batch", (mode,), session_id)

    def stop_process(self, session_id=None):
        return self._call("stop_process", session_id=session_id)

    def continue_manual_intervention(self, session_id=None):
        return self._call("continue_manual_intervention", session_id=session_id)

    def cancel_auto_next(self, session_id=None):
        return self._call("cancel_auto_next", session_id=session_id)

    def run_auto_next_now(self, session_id=None):
        return self._call("run_auto_next_now", session_id=session_id)

    def list_accounts(self, session_id=None):
        return self._call("list_accounts", session_id=session_id)

    def select_account(self, account_id, session_id=None):
        return self._call("select_account", (account_id,), session_id)

    def add_account(self, name, session_id=None):
        return self._call("add_account", (name,), session_id)

    def rename_account(self, account_id, name, session_id=None):
        return self._call("rename_account", (account_id, name), session_id)

    def remove_account(self, account_id, session_id=None):
        return self._call("remove_account", (account_id,), session_id)

    def login_account(self, account_id, session_id=None):
        return self._call("login_account", (account_id,), session_id)

    def set_language(self, language):
        return self._call("set_language", (language,))

    def set_theme(self, theme):
        return self._call("set_theme", (theme,))

    def minimize_window(self):
        return self._call("minimize_window")

    def move_window(self, x, y):
        return self._call("move_window", (x, y))

    def toggle_maximize_window(self):
        return self._call("toggle_maximize_window")

    def close_window(self):
        return self._call("close_window")

    def open_output_folder(self, session_id=None):
        return self._call("open_output_folder", session_id=session_id)

    def copy_log(self, session_id=None):
        return self._call("copy_log", session_id=session_id)

    def export_log(self, session_id=None):
        return self._call("export_log", session_id=session_id)

    def clear_log(self, session_id=None):
        return self._call("clear_log", session_id=session_id)

    def confirm_existing_output(self, session_id=None):
        return self._call("confirm_existing_output", session_id=session_id)


def run_packaged_worker() -> int:
    try:
        import run_chatgpt_batch

        return int(run_chatgpt_batch.run_guarded() or 0)
    except Exception:
        # The parent owns error reporting. An unhandled exception in a
        # windowed EXE would instead leave a blocking PyInstaller dialog.
        import traceback

        stream = sys.stderr or sys.stdout
        if stream is not None:
            traceback.print_exc(file=stream)
        return 1


def run_self_test() -> int:
    api = SessionManager()
    try:
        initial = api._invoke("get_initial_state")
        checks = {
            "controller": all(item.controller.__class__.__name__ == "DesktopController" for item in api.sessions.values()),
            "four_sessions": tuple(initial.get("data", {}).get("sessions", {})) == WORKFLOW_IDS,
            "initial_state": initial.get("ok") is True,
            "local_assets": all((RESOURCE_ROOT / "ui" / name).is_file() for name in ("index.html", "styles.css", "app.js")),
            "default_shell_untouched": (api.app_dir / "app.pyw").is_file() or bool(getattr(sys, "frozen", False)),
        }
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 0 if all(checks.values()) else 1
    finally:
        api._shutdown()


def run_webview() -> None:
    """Run the production web shell with a startup-only typed boundary."""
    initialized = False
    api = None
    try:
        if not UI_ENTRYPOINT.is_file():
            raise FileNotFoundError(f"Local UI entrypoint not found: {UI_ENTRYPOINT}")
        try:
            import webview
        except ImportError as exc:
            raise RuntimeError(
                "pywebview is not installed; use --tk for the CustomTkinter shell."
            ) from exc

        api = SessionManager()
        bridge = WebBridge(api)
        set_windows_app_user_model_id()
        window = webview.create_window(
            "ChatGPT Batch Translator",
            url=str(UI_ENTRYPOINT),
            js_api=bridge,
            width=1180,
            height=820,
            min_size=(900, 620),
            resizable=True,
            frameless=True,
            background_color="#E8EEF7",
            vibrancy=sys.platform == "darwin",
            text_select=True,
            easy_drag=sys.platform != "darwin",
        )
        if window is None:
            raise RuntimeError("pywebview did not create a window")
        api._attach_window(window)

        def on_initialized(renderer):
            nonlocal initialized
            initialized = True
            api._set_renderer(renderer)

        def on_loaded():
            enable_windows_taskbar_minimize(window)
            api._start_dispatcher()

        def on_shown():
            enable_windows_taskbar_minimize(window)

        def on_closed():
            api._shutdown()

        window.events.initialized += on_initialized
        window.events.loaded += on_loaded
        if hasattr(window.events, "shown"):
            window.events.shown += on_shown
        window.events.closed += on_closed
        if hasattr(window.events, "closing"):
            window.events.closing += api._confirm_close
        icon = str(WINDOWS_ICON_FILE) if WINDOWS_ICON_FILE.is_file() else None
        # easy_drag=True lets the user drag the frameless window from any empty
        # chrome region. Buttons/inputs opt out via [data-window-drag="no"].
        webview.start(
            http_server=True,
            private_mode=True,
            icon=icon,
        )
    except Exception as exc:
        if not initialized:
            if api is not None:
                api._shutdown()
            raise WebShellStartupError(str(exc)) from exc
        raise


def main() -> None:
    run_webview()


if __name__ == "__main__":
    if "--worker" in sys.argv:
        raise SystemExit(run_packaged_worker())
    if "--self-test" in sys.argv:
        raise SystemExit(run_self_test())
    try:
        main()
    except Exception as exc:
        print(f"Web UI startup failed: {exc}", file=sys.stderr)
        print("CustomTkinter remains available via: python app.pyw --tk", file=sys.stderr)
        raise SystemExit(1)
