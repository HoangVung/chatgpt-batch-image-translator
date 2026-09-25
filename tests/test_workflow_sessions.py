import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.runtime import apply_form_settings, load_settings, save_settings
from desktop.web_api import WebApi
from desktop.webview_app import WebBridge
from desktop.workflow_sessions import SessionManager
from desktop_controller import DesktopController
from test_web_api import FakeScheduler, Factory, FakeThread


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.factories = {}
        self.stopped = []
        self.registry_patch = patch("resource_guard.registry_dir", return_value=self.root / "locks")
        self.registry_patch.start()

        def factory(**kwargs):
            scheduler, process_factory = FakeScheduler(), Factory()
            self.factories[kwargs["session_id"]] = process_factory
            controller = DesktopController(scheduler, popen_factory=process_factory, thread_factory=FakeThread,
                                           process_tree_terminator=self.stopped.append)
            return WebApi(scheduler=scheduler, controller=controller, **kwargs)

        self.manager = SessionManager(app_dir=ROOT, data_dir=self.root, api_factory=factory)
        self.bridge = WebBridge(self.manager)
        for key, api in self.manager.sessions.items():
            source = self.root / (key + "-source")
            source.mkdir()
            api.settings.update(image_folder=str(source), download_folder=str(self.root / (key + "-output")))

    def tearDown(self):
        self.manager._shutdown()
        self.registry_patch.stop()
        self.temp.cleanup()

    def test_second_defaults_do_not_clone_book_or_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(app_dir=ROOT, data_dir=Path(directory))
            try:
                data = manager._invoke("get_initial_state")["data"]["sessions"]
                self.assertEqual(len(data), 2)
                a, b = data["book-1"]["settings"], data["book-2"]["settings"]
                self.assertEqual(b["image_folder"], "")
                self.assertEqual(b["download_folder"], "")
                self.assertNotEqual(a["profile_dir"], b["profile_dir"])
                self.assertFalse((Path(directory) / "app_settings.json").exists())
            finally:
                manager._shutdown()

    def test_parallel_start_uses_complete_distinct_snapshots(self):
        responses = {}
        barrier = threading.Barrier(2)
        def start(key):
            barrier.wait()
            responses[key] = self.bridge.start_batch("main", key)
        threads = [threading.Thread(target=start, args=(key,)) for key in self.manager.sessions]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        for key, response in responses.items():
            self.assertTrue(response["ok"], response)
            env = self.factories[key].calls[0][1]["env"]
            snapshot = json.loads(Path(env["BATCH_TRANSLATOR_SETTINGS_FILE"]).read_text(encoding="utf-8"))
            self.assertEqual(snapshot["chatgpt_accounts"], self.manager.sessions[key].settings["chatgpt_accounts"])
            self.assertEqual(snapshot["download_folder"], env["DOWNLOAD_FOLDER"])
        a, b = [self.factories[key].calls[0][1]["env"] for key in self.manager.sessions]
        for field in ("PROFILE_DIR", "DOWNLOAD_FOLDER", "BATCH_TRANSLATOR_SETTINGS_FILE"):
            self.assertNotEqual(a[field], b[field])
        self.assertNotIn("BATCH_TRANSLATOR_SETTINGS_FILE", os.environ)

    def test_same_tab_concurrent_start_only_creates_one_process(self):
        barrier = threading.Barrier(2)
        def start():
            barrier.wait()
            self.bridge.start_batch("main", "book-1")
        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        self.assertEqual(len(self.factories["book-1"].calls), 1)

    def test_conflicting_fallback_or_output_is_blocked_before_launch(self):
        a, b = self.manager.sessions.values()
        original = b.settings["download_folder"]
        b.settings["download_folder"] = a.settings["download_folder"]
        self.assertFalse(self.bridge.start_batch("main", "book-2")["ok"])
        b.settings["download_folder"] = original
        b.settings["chatgpt_accounts"].append(dict(a.settings["chatgpt_accounts"][0], id="borrowed"))
        self.assertFalse(self.bridge.start_batch("main", "book-2")["ok"])
        self.assertEqual(self.factories["book-2"].calls, [])

    def test_stop_continue_and_logs_are_isolated(self):
        for key in self.manager.sessions:
            self.assertTrue(self.bridge.start_batch("main", key)["ok"])
        a, b = self.manager.sessions.values()
        self.bridge.continue_manual_intervention("book-1")
        self.assertEqual(a.controller.process.stdin.writes, ["\n"])
        self.assertEqual(b.controller.process.stdin.writes, [])
        b.controller.append_log("book B\n")
        self.bridge.clear_log("book-1")
        self.assertIn("book B", "".join(b.controller.log_history))
        self.bridge.stop_process("book-1")
        self.assertEqual(self.stopped, [a.controller.process])
        self.assertTrue(b.controller.is_running())

    def test_export_startup_log_does_not_turn_new_output_into_legacy_output(self):
        self.assertTrue(self.bridge.start_batch("main", "book-1")["ok"])
        api = self.manager.sessions["book-1"]
        result = self.bridge.export_log("book-1")
        self.assertTrue(result["ok"], result)
        output = Path(api.settings["download_folder"])
        self.assertTrue((output / "workflow_output.json").exists())
        self.assertTrue((output / "process_log.txt").exists())

    def test_account_switch_auto_next_events_keep_session(self):
        a, b = self.manager.sessions.values()
        self.bridge.add_account("Fallback A", "book-1")
        account = a.settings["chatgpt_accounts"][-1]
        a.controller.handle_worker_output('__ACCOUNT_EVENT__=' + json.dumps({"event": "account_switched", "account_id": account["id"]}))
        a._dispatch_once()
        a.controller.schedule_auto_next()
        self.assertTrue(self.bridge.run_auto_next_now("book-1")["ok"])
        self.assertEqual(self.factories["book-1"].calls[-1][1]["env"]["PROFILE_DIR"], account["profile_dir"])
        self.assertEqual(b.settings["active_chatgpt_account_id"], "default")
        self.assertFalse(b.controller.state.auto_next_active)
        self.assertTrue(all(event["session_id"] == "book-1" for event in a.sent_events))

    def test_save_other_tab_and_preferences_do_not_cancel_timer(self):
        a, b = self.manager.sessions.values()
        a.controller.schedule_auto_next()
        response = self.bridge.save_settings({"batch_size": "3"}, "book-2")
        self.assertTrue(response["ok"], response)
        self.assertTrue(a.controller.state.auto_next_active)
        self.assertTrue(self.bridge.set_theme("dark")["ok"])
        self.assertTrue(a.controller.state.auto_next_active)
        self.assertEqual(b.settings["theme"], "dark")
        restored = load_settings(b.settings_path, b.defaults)
        self.assertEqual(restored["batch_size"], "3")

    def test_editing_running_session_and_unknown_session_are_rejected(self):
        self.bridge.start_batch("main", "book-1")
        self.assertFalse(self.bridge.save_settings({"batch_size": "7"}, "book-1")["ok"])
        self.assertFalse(self.bridge.stop_process("unknown")["ok"])
        self.assertFalse(self.manager._invoke("_shutdown")["ok"])

    def test_profile_change_does_not_mutate_old_settings(self):
        api = self.manager.sessions["book-1"]
        previous = api.settings["chatgpt_accounts"][0]["profile_dir"]
        updated = apply_form_settings(api.settings, {"profile_dir": str(self.root / "new-profile")}, api.data_dir)
        self.assertEqual(api.settings["chatgpt_accounts"][0]["profile_dir"], previous)
        self.assertNotEqual(updated["chatgpt_accounts"][0]["profile_dir"], previous)

    def test_legacy_output_requires_explicit_confirmation_and_preserves_files(self):
        api = self.manager.sessions["book-1"]
        output = Path(api.settings["download_folder"])
        output.mkdir()
        existing = output / "old.png"
        existing.write_bytes(b"existing bytes")
        self.assertFalse(self.bridge.start_batch("main", "book-1")["ok"])
        with patch("resource_guard.registry_dir", return_value=self.root / "locks"):
            result = self.bridge.confirm_existing_output("book-1")
        self.assertTrue(result["ok"], result)
        self.assertEqual(existing.read_bytes(), b"existing bytes")
        self.assertTrue(self.bridge.start_batch("main", "book-1")["ok"])


if __name__ == "__main__":
    unittest.main()
