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
        start_kwargs = {}

        def start(**kwargs):
            start_kwargs.update(kwargs)

        fake_webview = SimpleNamespace(create_window=lambda *args, **kwargs: window, start=start)

        with (
            patch.object(webview_app, "WebApi", FakeApi),
            patch.object(webview_app, "set_windows_app_user_model_id") as set_identity,
            patch.dict(sys.modules, {"webview": fake_webview}),
        ):
            webview_app.run_webview()

        set_identity.assert_called_once_with()
        self.assertEqual(start_kwargs["icon"], str(webview_app.WINDOWS_ICON_FILE))


if __name__ == "__main__":
    unittest.main()
