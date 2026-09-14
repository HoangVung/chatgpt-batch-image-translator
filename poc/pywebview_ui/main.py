"""Disposable pywebview proof of concept for the desktop UI stack."""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any

import webview


POC_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
UI_ENTRYPOINT = POC_DIR / "ui" / "index.html"


def success(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def failure(error: Exception | str) -> dict[str, Any]:
    return {"ok": False, "error": str(error)}


class PocApi:
    """Small, explicit bridge. No application controller is exposed."""

    def __init__(self) -> None:
        self._window: Any = None
        self._renderer = "initializing"
        self._python_message_id = 0

    def attach_window(self, window: Any) -> None:
        self._window = window

    def set_renderer(self, renderer: Any) -> None:
        self._renderer = str(renderer or "unknown")

    def get_platform_info(self) -> dict[str, Any]:
        return success(
            {
                "system": platform.system(),
                "sys_platform": sys.platform,
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "renderer": self._renderer,
                "frozen": bool(getattr(sys, "frozen", False)),
            }
        )

    def echo(self, message: Any) -> dict[str, Any]:
        try:
            if not isinstance(message, str):
                raise TypeError("message must be a string")
            if len(message) > 2_000:
                raise ValueError("message is too long")
            return success({"message": message})
        except (TypeError, ValueError) as exc:
            return failure(exc)

    def choose_folder(self) -> dict[str, Any]:
        try:
            if self._window is None:
                raise RuntimeError("window is not ready")
            selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
            path = selected[0] if selected else None
            return success({"path": path, "cancelled": path is None})
        except Exception as exc:
            return failure(exc)

    def get_initial_state(self) -> dict[str, Any]:
        platform_response = self.get_platform_info()
        return success(
            {
                "platform": platform_response["data"],
                "appearance": "system",
                "capabilities": {
                    "native_titlebar": True,
                    "resizable": True,
                    "native_folder_picker": True,
                    "local_assets_only": True,
                    "macos_vibrancy_requested": sys.platform == "darwin",
                },
            }
        )

    def trigger_python_to_javascript(self, message: Any) -> dict[str, Any]:
        try:
            if not isinstance(message, str):
                raise TypeError("message must be a string")
            self._python_message_id += 1
            payload = {
                "id": self._python_message_id,
                "message": message,
                "source": "Python window.run_js",
            }
            self._push_to_javascript(payload)
            return success({"delivered": True, "id": self._python_message_id})
        except Exception as exc:
            return failure(exc)

    def _push_to_javascript(self, payload: dict[str, Any]) -> None:
        if self._window is None:
            raise RuntimeError("window is not ready")
        serialized = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        self._window.run_js(f"window.pocReceiveFromPython({serialized});")


def run_self_test() -> int:
    class FakeWindow:
        def __init__(self) -> None:
            self.script = ""

        def run_js(self, script: str) -> None:
            self.script = script

    api = PocApi()
    fake_window = FakeWindow()
    api.attach_window(fake_window)
    api.set_renderer("self-test")

    checks = {
        "platform_contract": api.get_platform_info().get("ok") is True,
        "echo_contract": api.echo("hello").get("data", {}).get("message") == "hello",
        "invalid_echo": api.echo(123).get("ok") is False,
        "initial_state": api.get_initial_state().get("ok") is True,
        "python_to_js": api.trigger_python_to_javascript("hello JS").get("ok") is True
        and "pocReceiveFromPython" in fake_window.script,
        "local_entrypoint": UI_ENTRYPOINT.is_file(),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


def main() -> None:
    if not UI_ENTRYPOINT.is_file():
        raise FileNotFoundError(f"Local UI entrypoint not found: {UI_ENTRYPOINT}")

    api = PocApi()
    window = webview.create_window(
        "pywebview Liquid Glass POC",
        url=str(UI_ENTRYPOINT),
        js_api=api,
        width=1060,
        height=720,
        min_size=(760, 520),
        resizable=True,
        frameless=False,
        background_color="#E9EEF7",
        vibrancy=sys.platform == "darwin",
        text_select=True,
    )
    if window is None:
        raise RuntimeError("pywebview did not create a window")

    api.attach_window(window)

    def on_initialized(renderer: Any) -> None:
        api.set_renderer(renderer)

    def on_loaded() -> None:
        api.trigger_python_to_javascript("Local UI loaded successfully")

    window.events.initialized += on_initialized
    window.events.loaded += on_loaded
    webview.start(http_server=True, private_mode=True)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_self_test())
    main()
