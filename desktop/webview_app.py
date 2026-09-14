"""Production pywebview shell entrypoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop.web_api import WebApi


RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
UI_ENTRYPOINT = RESOURCE_ROOT / "ui" / "index.html"


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

    def get_initial_state(self):
        return self._api.get_initial_state()

    def get_platform_capabilities(self):
        return self._api.get_platform_capabilities()

    def save_settings(self, payload):
        return self._api.save_settings(payload)

    def choose_folder(self, kind):
        return self._api.choose_folder(kind)

    def start_batch(self, mode):
        return self._api.start_batch(mode)

    def stop_process(self):
        return self._api.stop_process()

    def continue_manual_intervention(self):
        return self._api.continue_manual_intervention()

    def cancel_auto_next(self):
        return self._api.cancel_auto_next()

    def run_auto_next_now(self):
        return self._api.run_auto_next_now()

    def list_accounts(self):
        return self._api.list_accounts()

    def select_account(self, account_id):
        return self._api.select_account(account_id)

    def add_account(self, name):
        return self._api.add_account(name)

    def rename_account(self, account_id, name):
        return self._api.rename_account(account_id, name)

    def remove_account(self, account_id):
        return self._api.remove_account(account_id)

    def login_account(self, account_id):
        return self._api.login_account(account_id)

    def set_language(self, language):
        return self._api.set_language(language)

    def set_theme(self, theme):
        return self._api.set_theme(theme)

    def open_output_folder(self):
        return self._api.open_output_folder()

    def copy_log(self):
        return self._api.copy_log()

    def export_log(self):
        return self._api.export_log()

    def clear_log(self):
        return self._api.clear_log()


def run_packaged_worker() -> int:
    import run_chatgpt_batch

    return int(run_chatgpt_batch.main() or 0)


def run_self_test() -> int:
    api = WebApi()
    try:
        initial = api.get_initial_state()
        checks = {
            "controller": api.controller.__class__.__name__ == "DesktopController",
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

        api = WebApi()
        bridge = WebBridge(api)
        window = webview.create_window(
            "ChatGPT Batch Translator",
            url=str(UI_ENTRYPOINT),
            js_api=bridge,
            width=1180,
            height=820,
            min_size=(900, 620),
            resizable=True,
            frameless=False,
            background_color="#E8EEF7",
            vibrancy=sys.platform == "darwin",
            text_select=True,
        )
        if window is None:
            raise RuntimeError("pywebview did not create a window")
        api._attach_window(window)

        def on_initialized(renderer):
            nonlocal initialized
            initialized = True
            api._set_renderer(renderer)

        def on_loaded():
            api._start_dispatcher()

        def on_closed():
            api._shutdown()

        window.events.initialized += on_initialized
        window.events.loaded += on_loaded
        window.events.closed += on_closed
        webview.start(http_server=True, private_mode=True)
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
