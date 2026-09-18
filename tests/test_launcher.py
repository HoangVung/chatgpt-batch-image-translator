import ctypes
import io
import runpy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
namespace = runpy.run_path(str(PROJECT_ROOT / "app.pyw"), run_name="launcher_under_test")
select_launch_mode = namespace["select_launch_mode"]
try_web_shell = namespace["try_web_shell"]
from desktop import webview_app


class StartupError(RuntimeError):
    pass


class EventHook:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeApi:
    instances = []

    def __init__(self):
        self.window = None
        self.renderer = None
        self.shutdown_calls = 0
        self.__class__.instances.append(self)

    def _attach_window(self, window):
        self.window = window

    def _set_renderer(self, renderer):
        self.renderer = renderer

    def _start_dispatcher(self):
        pass

    def _shutdown(self):
        self.shutdown_calls += 1


class LauncherTests(unittest.TestCase):
    def setUp(self):
        FakeApi.instances.clear()

    def test_windows_default_selects_webview(self):
        self.assertEqual(select_launch_mode(["app.pyw"], "win32"), "web")

    def test_tk_flag_selects_legacy_shell(self):
        self.assertEqual(select_launch_mode(["app.pyw", "--tk"], "win32"), "tk")

    def test_non_windows_keeps_existing_tk_default(self):
        self.assertEqual(select_launch_mode(["app.pyw"], "linux"), "tk")

    def test_worker_and_self_test_bypass_both_gui_shells(self):
        self.assertEqual(select_launch_mode(["app.pyw", "--worker"], "win32"), "worker")
        self.assertEqual(select_launch_mode(["app.pyw", "--self-test"], "win32"), "self-test")

    def test_webview_success_does_not_request_tk_fallback(self):
        calls = []

        self.assertTrue(try_web_shell(lambda: calls.append("web"), StartupError))
        self.assertEqual(calls, ["web"])

    def test_startup_failure_requests_one_tk_fallback(self):
        calls = []
        errors = io.StringIO()

        def fail_once():
            calls.append("web")
            raise StartupError("missing runtime")

        self.assertFalse(try_web_shell(fail_once, StartupError, errors))
        self.assertEqual(calls, ["web"])
        self.assertIn("falling back to Tk shell", errors.getvalue())

    def test_windowed_build_without_stderr_still_requests_fallback(self):
        def fail_without_console():
            raise StartupError("missing runtime")

        with patch.object(sys, "stderr", None):
            self.assertFalse(try_web_shell(fail_without_console, StartupError))

    def test_post_start_runtime_error_is_not_converted_to_fallback(self):
        def fail_after_start():
            raise ValueError("workflow failure")

        with self.assertRaisesRegex(ValueError, "workflow failure"):
            try_web_shell(fail_after_start, StartupError, io.StringIO())

    def test_webview_failure_before_initialized_is_typed_for_fallback(self):
        window = SimpleNamespace(events=SimpleNamespace(
            initialized=EventHook(), loaded=EventHook(), closed=EventHook()
        ))
        fake_webview = SimpleNamespace(
            create_window=lambda *args, **kwargs: window,
            start=lambda **kwargs: (_ for _ in ()).throw(OSError("WebView2 unavailable")),
        )

        with patch.object(webview_app, "WebApi", FakeApi), patch.dict(sys.modules, {"webview": fake_webview}):
            with self.assertRaisesRegex(webview_app.WebShellStartupError, "WebView2 unavailable"):
                webview_app.run_webview()

        self.assertEqual(FakeApi.instances[0].shutdown_calls, 1)

    def test_webview_failure_after_initialized_is_not_fallback_eligible(self):
        window = SimpleNamespace(events=SimpleNamespace(
            initialized=EventHook(), loaded=EventHook(), closed=EventHook()
        ))

        def fail_after_initialized(**kwargs):
            window.events.initialized.handlers[0]("edgechromium")
            raise ValueError("runtime failure")

        fake_webview = SimpleNamespace(create_window=lambda *args, **kwargs: window, start=fail_after_initialized)

        with patch.object(webview_app, "WebApi", FakeApi), patch.dict(sys.modules, {"webview": fake_webview}):
            with self.assertRaisesRegex(ValueError, "runtime failure"):
                webview_app.run_webview()

        self.assertEqual(FakeApi.instances[0].renderer, "edgechromium")

    def test_webview_passes_branded_icon_to_native_shell(self):
        window = SimpleNamespace(events=SimpleNamespace(
            initialized=EventHook(), loaded=EventHook(), closed=EventHook()
        ))
        create_kwargs = {}
        start_kwargs = {}

        def create_window(*args, **kwargs):
            create_kwargs.update(kwargs)
            return window

        def start(**kwargs):
            start_kwargs.update(kwargs)

        fake_webview = SimpleNamespace(create_window=create_window, start=start)

        with (
            patch.object(webview_app, "WebApi", FakeApi),
            patch.object(webview_app, "set_windows_app_user_model_id") as set_identity,
            patch.dict(sys.modules, {"webview": fake_webview}),
        ):
            webview_app.run_webview()

        set_identity.assert_called_once_with()
        self.assertEqual(start_kwargs["icon"], str(webview_app.WINDOWS_ICON_FILE))
        self.assertNotIn("easy_drag", start_kwargs)
        self.assertEqual(create_kwargs.get("easy_drag"), sys.platform != "darwin")

    def test_webview_wires_taskbar_minimize_on_load_and_show(self):
        window = SimpleNamespace(events=SimpleNamespace(
            initialized=EventHook(), loaded=EventHook(), shown=EventHook(), closed=EventHook()
        ))
        fake_webview = SimpleNamespace(
            create_window=lambda *args, **kwargs: window,
            start=lambda **kwargs: None,
        )

        with (
            patch.object(webview_app, "WebApi", FakeApi),
            patch.object(webview_app, "set_windows_app_user_model_id"),
            patch.object(webview_app, "enable_windows_taskbar_minimize") as mock_enable,
            patch.dict(sys.modules, {"webview": fake_webview}),
        ):
            webview_app.run_webview()
            for handler in window.events.loaded.handlers:
                handler()
            for handler in window.events.shown.handlers:
                handler()

        self.assertEqual(mock_enable.call_count, 2)
        mock_enable.assert_called_with(window)

    def test_enable_windows_taskbar_minimize_logic(self):
        from desktop.window_identity import (
            enable_windows_taskbar_minimize,
            WS_MINIMIZEBOX,
            WS_SYSMENU,
        )

        # 1. Non-windows returns False
        with patch.object(sys, "platform", "darwin"):
            self.assertFalse(enable_windows_taskbar_minimize(12345))

        # 2. None / invalid target returns False
        with patch.object(sys, "platform", "win32"):
            self.assertFalse(enable_windows_taskbar_minimize(None))
            self.assertFalse(enable_windows_taskbar_minimize(SimpleNamespace()))

        # 3. Valid hwnd updates styles with WS_MINIMIZEBOX and WS_SYSMENU
        styles = [0x16010000]
        pos_calls = []

        def mock_get(hwnd, index):
            return styles[0]

        def mock_set(hwnd, index, new_style):
            styles[0] = new_style
            return new_style

        def mock_set_pos(hwnd, after, x, y, cx, cy, flags):
            pos_calls.append(flags)
            return 1

        mock_user32 = SimpleNamespace(
            GetWindowLongPtrW=mock_get,
            SetWindowLongPtrW=mock_set,
            SetWindowPos=mock_set_pos,
        )

        with (
            patch.object(sys, "platform", "win32"),
            patch.object(ctypes.windll, "user32", mock_user32, create=True),
        ):
            # Target as int
            result = enable_windows_taskbar_minimize(1001)
            self.assertTrue(result)
            self.assertTrue(styles[0] & WS_MINIMIZEBOX)
            self.assertTrue(styles[0] & WS_SYSMENU)
            self.assertEqual(len(pos_calls), 1)

            # Idempotent call
            result2 = enable_windows_taskbar_minimize(1001)
            self.assertTrue(result2)
            self.assertEqual(len(pos_calls), 1)  # No extra SetWindowPos

            # Target as object with .native.Handle (IntPtr simulator)
            class MockIntPtr:
                def ToInt64(self):
                    return 2002

            mock_win = SimpleNamespace(native=SimpleNamespace(Handle=MockIntPtr()))
            result3 = enable_windows_taskbar_minimize(mock_win)
            self.assertTrue(result3)


if __name__ == "__main__":
    unittest.main()
