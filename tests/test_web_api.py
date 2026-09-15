import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from desktop.runtime import build_process_launch, load_settings, make_default_settings
from desktop.web_api import WebApi
from desktop.webview_app import WebBridge
from desktop_controller import ControllerEvent, DesktopController


class FakeScheduler:
    def __init__(self):
        self.closed = False
        self.handles = []

    def call_later(self, delay_ms, callback):
        handle = {"delay": delay_ms, "callback": callback}
        self.handles.append(handle)
        return handle

    def cancel(self, handle):
        handle["cancelled"] = True

    def shutdown(self):
        self.closed = True


class FakeStdin:
    def __init__(self):
        self.writes = []

    def write(self, text):
        self.writes.append(text)

    def flush(self):
        pass


class FakeProcess:
    def __init__(self):
        self.return_code = None
        self.stdin = FakeStdin()
        self.stdout = []
        self.pid = 101

    def poll(self):
        return self.return_code

    def wait(self):
        return self.return_code or 0


class FakeThread:
    def __init__(self, **kwargs):
        self.started = False

    def start(self):
        self.started = True


class Factory:
    def __init__(self):
        self.calls = []
        self.processes = []

    def __call__(self, command, **kwargs):
        process = FakeProcess()
        self.calls.append((command, kwargs))
        self.processes.append(process)
        return process


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        self.settings_path = self.data_dir / "app_settings.json"
        self.scheduler = FakeScheduler()
        self.factory = Factory()
        self.terminated = []
        controller = DesktopController(
            self.scheduler,
            popen_factory=self.factory,
            thread_factory=FakeThread,
            process_tree_terminator=self.terminated.append,
        )
        self.api = WebApi(
            controller=controller,
            scheduler=self.scheduler,
            app_dir=PROJECT_ROOT,
            data_dir=self.data_dir,
            settings_path=self.settings_path,
        )

    def tearDown(self):
        self.api._shutdown()
        self.temp.cleanup()

    def test_get_initial_state_is_single_complete_envelope(self):
        response = self.api.get_initial_state()
        self.assertTrue(response["ok"])
        data = response["data"]
        self.assertEqual(data["settings"]["service"], "chatgpt")
        self.assertIn("controller", data)
        self.assertIn("localization", data)
        self.assertIn("capabilities", data)
        self.assertNotIn("controller_object", data)

    def test_public_bridge_surface_is_explicit_and_contains_no_execution_escape_hatch(self):
        public = {
            name for name in dir(self.api)
            if not name.startswith("_") and callable(getattr(self.api, name))
        }
        self.assertEqual(public, {
            "add_account", "cancel_auto_next", "choose_folder", "clear_log", "close_window",
            "continue_manual_intervention", "copy_log", "export_log", "get_initial_state",
            "get_platform_capabilities", "list_accounts", "login_account", "minimize_window",
            "open_output_folder", "remove_account", "rename_account", "run_auto_next_now",
            "save_settings", "select_account", "set_language", "set_theme", "start_batch",
            "stop_process", "toggle_maximize_window",
        })

    def test_pywebview_bridge_contains_no_public_runtime_state(self):
        bridge = WebBridge(self.api)
        public = {name for name in dir(bridge) if not name.startswith("_")}
        self.assertEqual(public, {
            "add_account", "cancel_auto_next", "choose_folder", "clear_log", "close_window",
            "continue_manual_intervention", "copy_log", "export_log", "get_initial_state",
            "get_platform_capabilities", "list_accounts", "login_account", "minimize_window",
            "open_output_folder", "remove_account", "rename_account", "run_auto_next_now",
            "save_settings", "select_account", "set_language", "set_theme", "start_batch",
            "stop_process", "toggle_maximize_window",
        })
        self.assertTrue(all(callable(getattr(bridge, name)) for name in public))

    def test_start_batch_accepts_only_whitelisted_modes(self):
        self.assertFalse(self.api.start_batch("login")["ok"])
        self.assertFalse(self.api.start_batch("main && calc")["ok"])
        self.assertTrue(self.api.start_batch("main")["ok"])
        self.assertEqual(self.factory.calls[0][1]["env"]["RUN_MODE"], "main")
        self.assertFalse(self.api.start_batch("retry")["ok"])

    def test_main_retry_and_force_launch_contracts(self):
        for mode in ("main", "retry", "force"):
            with self.subTest(mode=mode):
                self.api.controller.process = None
                self.api.controller.state.running = False
                if mode == "force":
                    self.api.settings["start_from"] = "12.png"
                response = self.api.start_batch(mode)
                self.assertTrue(response["ok"], response)
                self.assertEqual(self.factory.calls[-1][1]["env"]["RUN_MODE"], mode)

    def test_save_validation_and_tk_schema_compatibility(self):
        payload = {
            "image_folder": "D:/source",
            "download_folder": "D:/output",
            "profile_dir": "D:/profile",
            "batch_size": "7",
            "start_from": "",
            "auto_next_enabled": True,
            "auto_next_delay_minutes": "3",
            "auto_account_fallback_enabled": True,
            "theme": "dark",
            "language": "en",
            "service": "chatgpt",
        }
        self.assertTrue(self.api.save_settings(payload)["ok"])
        loaded = load_settings(self.settings_path, make_default_settings(self.data_dir))
        self.assertEqual(loaded["batch_size"], "7")
        self.assertEqual(loaded["theme"], "dark")
        self.assertEqual(set(loaded), set(make_default_settings(self.data_dir)))
        self.assertFalse(self.api.save_settings({"theme": "neon"})["ok"])
        self.assertFalse(self.api.save_settings({"run_command": "calc"})["ok"])

    def test_save_marks_intervention_only_when_run_configuration_changes(self):
        self.assertTrue(self.api.start_batch("main")["ok"])

        same_batch_size = self.api.settings["batch_size"]
        self.assertTrue(self.api.save_settings({"batch_size": same_batch_size})["ok"])
        self.assertFalse(self.api.controller.state.current_run_intervened)

        self.assertTrue(self.api.save_settings({"theme": "dark"})["ok"])
        self.assertFalse(self.api.controller.state.current_run_intervened)

        self.assertTrue(self.api.save_settings({"batch_size": "11"})["ok"])
        self.assertTrue(self.api.controller.state.current_run_intervened)

    def test_folder_kind_is_whitelisted(self):
        self.assertFalse(self.api.choose_folder("arbitrary")["ok"])
        self.api._attach_window(types.SimpleNamespace(create_file_dialog=lambda _kind: ["D:/picked"]))
        fake_webview = types.SimpleNamespace(FileDialog=types.SimpleNamespace(FOLDER="folder"))
        with patch.dict(sys.modules, {"webview": fake_webview}):
            chosen = self.api.choose_folder("source")
        self.assertTrue(chosen["ok"])
        self.assertEqual(chosen["data"]["path"], "D:/picked")

    def test_stop_continue_and_auto_commands_return_envelopes(self):
        self.assertTrue(self.api.start_batch("main")["ok"])
        self.api.controller.state.manual_action_required = True
        continued = self.api.continue_manual_intervention()
        self.assertTrue(continued["ok"])
        self.assertEqual(self.factory.processes[-1].stdin.writes, ["\n"])
        stopped = self.api.stop_process()
        self.assertTrue(stopped["ok"])
        self.assertEqual(self.terminated, [self.factory.processes[-1]])
        self.assertTrue(self.api.cancel_auto_next()["ok"])
        self.assertFalse(self.api.run_auto_next_now()["ok"])

    def test_run_now_consumes_controller_request_and_builds_fresh_launch(self):
        self.api.controller.state.auto_next_active = True
        response = self.api.run_auto_next_now()
        self.assertTrue(response["ok"], response)
        self.assertEqual(len(self.factory.calls), 1)
        self.assertEqual(self.factory.calls[0][1]["env"]["PROFILE_DIR"], self.api.settings["profile_dir"])

    def test_event_serialization_is_json_safe_sequenced_and_ordered(self):
        error = ValueError("safe message")
        self.api.controller._events.extend([
            ControllerEvent("first", {"path": Path("one"), "error": error}),
            ControllerEvent("second", {"value": float("nan")}),
        ])
        delivered = self.api._dispatch_once()
        original = [event for event in delivered if event["type"] in {"first", "second"}]
        self.assertEqual([event["type"] for event in original], ["first", "second"])
        self.assertLess(original[0]["sequence"], original[1]["sequence"])
        self.assertIsNone(original[1]["payload"]["value"])
        json.dumps(original)

    def test_runtime_config_supports_chatgpt_gemini_and_account_refresh(self):
        self.api.settings.update({
            "chatgpt_accounts": [
                {"id": "one", "name": "One", "profile_dir": "D:/one"},
                {"id": "two", "name": "Two", "profile_dir": "D:/two"},
            ],
            "active_chatgpt_account_id": "one",
            "service": "chatgpt",
        })
        chatgpt = build_process_launch(self.api.settings, "main", app_dir=PROJECT_ROOT, environ={}, os_name="posix")
        self.assertEqual(chatgpt.env["PROFILE_DIR"], "D:/one")
        self.api.controller._events.append(ControllerEvent("account_event", {"event": {"event": "account_switched", "account_id": "two"}}))
        self.api._dispatch_once()
        refreshed = build_process_launch(self.api.settings, "main", app_dir=PROJECT_ROOT, environ={}, os_name="posix")
        self.assertEqual(refreshed.env["PROFILE_DIR"], "D:/two")
        self.api.settings.update({"service": "gemini", "gemini_profile_dir": "D:/gemini"})
        gemini = build_process_launch(self.api.settings, "main", app_dir=PROJECT_ROOT, environ={}, os_name="posix")
        self.assertEqual(gemini.env["SERVICE"], "gemini")
        self.assertEqual(gemini.env["PROFILE_DIR"], "D:/gemini")
        frozen = build_process_launch(
            self.api.settings,
            "main",
            app_dir=PROJECT_ROOT,
            executable="TranslatorWeb.exe",
            frozen=True,
            environ={},
            os_name="posix",
        )
        self.assertEqual(frozen.command, ["TranslatorWeb.exe", "--worker"])
        self.assertEqual(frozen.env["PLAYWRIGHT_BROWSERS_PATH"], str(PROJECT_ROOT / "ms-playwright"))

    def test_account_crud_preserves_profiles_and_active_account(self):
        added = self.api.add_account("Business 2")
        self.assertTrue(added["ok"])
        active = added["data"]["active_id"]
        self.assertTrue(self.api.rename_account(active, "Primary")["ok"])
        self.assertTrue(self.api.select_account("default")["ok"])
        removed = self.api.remove_account(active)
        self.assertTrue(removed["ok"])
        self.assertEqual([account["id"] for account in removed["data"]["accounts"]], ["default"])
        persisted = load_settings(self.settings_path, make_default_settings(self.data_dir))
        self.assertEqual([account["id"] for account in persisted["chatgpt_accounts"]], ["default"])

    def test_public_profile_tracks_service_and_active_account(self):
        self.api.settings.update({
            "chatgpt_accounts": [
                {"id": "one", "name": "One", "profile_dir": "D:/one"},
                {"id": "two", "name": "Two", "profile_dir": "D:/two"},
            ],
            "active_chatgpt_account_id": "two",
            "profile_dir": "D:/stale",
            "gemini_profile_dir": "D:/gemini",
        })
        initial = self.api.get_initial_state()["data"]["settings"]
        self.assertEqual(initial["profile_dir"], "D:/two")
        saved = self.api.save_settings({"service": "gemini", "profile_dir": ""})
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["data"]["settings"]["profile_dir"], "D:/gemini")

    def test_account_and_process_events_update_python_owned_status_and_log(self):
        self.api.controller._events.extend([
            ControllerEvent("account_event", {"event": {
                "event": "job_waiting", "reason": "quota", "image": "12.png",
            }}),
            ControllerEvent("process_outcome", {
                "outcome": "needs_retry", "exit_code": 2, "job": {"failed": 3},
            }),
        ])
        self.api._dispatch_once()
        self.assertIn("quota", "".join(self.api.controller.log_history))
        self.assertEqual(self.api.status, {"key": "needs_retry_outcome", "params": {"failed": 3}})

    def test_export_copy_and_clear_log_use_python_history(self):
        self.api.settings["download_folder"] = str(self.data_dir / "output")
        self.api.controller.append_log("hello log")
        self.api._dispatch_once()
        exported = self.api.export_log()
        self.assertTrue(exported["ok"])
        self.assertEqual(Path(exported["data"]["path"]).read_text(encoding="utf-8"), "hello log")
        with patch.object(self.api, "_copy_text") as copy_text:
            self.assertTrue(self.api.copy_log()["ok"])
            copy_text.assert_called_once_with("hello log")
        self.assertTrue(self.api.clear_log()["ok"])
        self.assertEqual(self.api.controller.log_history, [])

    def test_open_output_creates_configured_folder_and_uses_native_shell(self):
        output = self.data_dir / "new-output"
        self.api.settings["download_folder"] = str(output)
        with patch("desktop.web_api.os.startfile", create=True) as startfile:
            response = self.api.open_output_folder()
        self.assertTrue(response["ok"])
        self.assertTrue(output.is_dir())
        startfile.assert_called_once_with(output)

    def test_static_frontend_is_local_vanilla_and_calls_narrow_bridge(self):
        html = (PROJECT_ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (PROJECT_ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        combined = html + js + (PROJECT_ROOT / "ui" / "styles.css").read_text(encoding="utf-8")
        self.assertNotRegex(combined, r"https?://")
        for forbidden in ("React", "Vue", "Svelte", "run_command", "execute(", "eval("):
            self.assertNotIn(forbidden, combined)
        self.assertIn("window.pywebview", js)
        self.assertIn("batchTranslatorReceive", js)


if __name__ == "__main__":
    unittest.main()
