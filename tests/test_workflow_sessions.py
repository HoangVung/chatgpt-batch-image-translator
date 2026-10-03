import json
import os
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from itertools import combinations
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.runtime import apply_form_settings, load_settings, make_default_settings, save_settings
from desktop.web_api import WebApi
from desktop.webview_app import WebBridge
from desktop.workflow_sessions import SessionManager, WORKFLOW_IDS
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

    def test_books34_controls_leave_stable_processes_state_and_settings_untouched(self):
        for key in ('book-1','book-2'):
            self.assertTrue(self.bridge.start_batch('main',key)['ok'])
        protected = {}
        for key in ('book-1','book-2'):
            api=self.manager.sessions[key]
            protected[key]=(api.controller.process, deepcopy(api.controller.state),
                            deepcopy(api.settings), api.settings_path.read_bytes(), list(api.sent_events))
        for key in ('book-3','book-4'):
            api=self.manager.sessions[key]
            api.controller.schedule_auto_next()
            self.assertTrue(self.bridge.cancel_auto_next(key)['ok'])
            self.assertTrue(self.bridge.add_account('New fallback',key)['ok'])
            account=api.settings['chatgpt_accounts'][-1]
            api.controller.handle_worker_output('__ACCOUNT_EVENT__='+json.dumps({'event':'account_switched','account_id':account['id']}))
            api._dispatch_once()
            api.controller.schedule_auto_next()
            self.assertTrue(self.bridge.run_auto_next_now(key)['ok'])
            self.assertEqual(self.factories[key].calls[-1][1]['env']['BATCH_TRANSLATOR_WORKER_VARIANT'],'books34')
            self.assertTrue(self.bridge.stop_process(key)['ok'])
        for key, before in protected.items():
            api=self.manager.sessions[key]
            self.assertIs(api.controller.process,before[0])
            self.assertEqual(api.controller.state,before[1])
            self.assertEqual(api.settings,before[2])
            self.assertEqual(api.settings_path.read_bytes(),before[3])
            self.assertEqual(list(api.sent_events),before[4])

    def test_secondary_defaults_do_not_clone_book_or_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(app_dir=ROOT, data_dir=Path(directory))
            try:
                data = manager._invoke("get_initial_state")["data"]["sessions"]
                self.assertEqual(tuple(data), WORKFLOW_IDS)
                for key in WORKFLOW_IDS[1:]:
                    settings = data[key]["settings"]
                    self.assertEqual(settings["image_folder"], "")
                    self.assertEqual(settings["download_folder"], "")
                    self.assertEqual(settings["start_from"], "")
                for field in ("profile_dir", "gemini_profile_dir"):
                    self.assertEqual(len({item["settings"][field] for item in data.values()}), 4)
                self.assertFalse((Path(directory) / "app_settings.json").exists())
            finally:
                manager._shutdown()

    def test_parallel_start_uses_complete_distinct_snapshots(self):
        responses = {}
        barrier = threading.Barrier(4)
        def start(key):
            barrier.wait()
            responses[key] = self.bridge.start_batch("main", key)
        threads = [threading.Thread(target=start, args=(key,)) for key in self.manager.sessions]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(set(responses), set(WORKFLOW_IDS))
        for key, response in responses.items():
            self.assertTrue(response["ok"], response)
            self.assertEqual(len(self.factories[key].calls), 1)
            env = self.factories[key].calls[0][1]["env"]
            snapshot = json.loads(Path(env["BATCH_TRANSLATOR_SETTINGS_FILE"]).read_text(encoding="utf-8"))
            self.assertEqual(snapshot["chatgpt_accounts"], self.manager.sessions[key].settings["chatgpt_accounts"])
            self.assertEqual(snapshot["download_folder"], env["DOWNLOAD_FOLDER"])
        environments = [self.factories[key].calls[0][1]["env"] for key in self.manager.sessions]
        for field in ("PROFILE_DIR", "DOWNLOAD_FOLDER", "BATCH_TRANSLATOR_SETTINGS_FILE"):
            self.assertEqual(len({env[field] for env in environments}), 4)
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
        a, b = (self.manager.sessions[key] for key in ("book-1", "book-2"))
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
        a, b = (self.manager.sessions[key] for key in ("book-1", "book-2"))
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
        a, b = (self.manager.sessions[key] for key in ("book-1", "book-2"))
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
        a, b = (self.manager.sessions[key] for key in ("book-1", "book-2"))
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

    def test_upgrade_preserves_stable_books_and_data_while_resetting_books34(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            originals, files = {}, {}
            for index, key in enumerate(WORKFLOW_IDS, 1):
                data_dir = root if key == "book-1" else root / "workflows" / key
                settings = make_default_settings(data_dir)
                settings.update(batch_size=str(index + 2), service="gemini" if index == 2 else "chatgpt",
                                start_from=f"{index}_1.jpg", theme="dark", auto_next_delay_minutes=str(index))
                settings["chatgpt_accounts"][0]["name"] = f"Existing account {index}"
                settings["chatgpt_accounts"].append({"id": "fallback", "name": f"Fallback {index}",
                                                    "profile_dir": str(data_dir / "fallback-profile")})
                path = data_dir / "app_settings.json"
                save_settings(path, settings)
                originals[key] = settings
                files[path] = path.read_bytes()
                output = Path(settings["download_folder"])
                output.mkdir(parents=True)
                for name in ("old.png", "progress.csv", "job_checkpoint.json"):
                    marker = output / name
                    marker.write_bytes(f"existing {key} {name}".encode())
                    files[marker] = marker.read_bytes()
            manager = SessionManager(app_dir=ROOT, data_dir=root)
            try:
                for key in WORKFLOW_IDS[:2]:
                    self.assertEqual(manager.sessions[key].settings, originals[key])
                for key, template in (("book-3", "book-1"), ("book-4", "book-2")):
                    api = manager.sessions[key]
                    self.assertEqual(api.settings["batch_size"], originals[template]["batch_size"])
                    self.assertEqual(api.settings["service"], originals[template]["service"])
                    self.assertEqual(api.settings["start_from"], "")
                    self.assertEqual((api.data_dir / "books34-setup-v1" / "app_settings.original.json").read_bytes(), files[api.settings_path])
                for path, contents in files.items():
                    if path.name == "app_settings.json" and path.parent.name in {"book-3", "book-4"}:
                        continue
                    self.assertEqual(path.read_bytes(), contents, str(path))
            finally:
                manager._shutdown()

    def test_new_books_inherit_only_run_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_default_settings(root)
            settings.update(service="gemini", batch_size="7", auto_next_enabled=False,
                            auto_next_delay_minutes="9", auto_account_fallback_enabled=False,
                            theme="dark", language="en", start_from="42_1.jpg")
            settings["chatgpt_accounts"].append({"id": "private", "name": "Existing fallback",
                                                "profile_dir": str(root / "private-profile")})
            save_settings(root / "app_settings.json", settings)
            manager = SessionManager(app_dir=ROOT, data_dir=root)
            try:
                for key in WORKFLOW_IDS[1:]:
                    other = manager.sessions[key]
                    for field in ("service", "batch_size", "auto_next_enabled", "auto_next_delay_minutes",
                                  "auto_account_fallback_enabled", "theme", "language"):
                        self.assertEqual(other.settings[field], settings[field])
                    self.assertEqual([a["id"] for a in other.settings["chatgpt_accounts"]], ["default"])
                    if key == "book-2":
                        self.assertEqual(other.settings["profile_dir"], str(other.data_dir / "chatgpt_auto_profile"))
                        self.assertEqual(other.settings["gemini_profile_dir"], str(other.data_dir / "gemini_auto_profile"))
                        self.assertFalse(other.settings_path.exists())
                    else:
                        self.assertIn("isolated-profiles", other.settings["profile_dir"])
                        self.assertEqual(other.settings["profile_dir"], other.settings["gemini_profile_dir"])
                        self.assertTrue(other.settings_path.exists())
            finally:
                manager._shutdown()

    def test_all_six_pairs_reject_conflicting_outputs_and_profiles(self):
        for first, second in combinations(WORKFLOW_IDS, 2):
            a, b = self.manager.sessions[first], self.manager.sessions[second]
            saved = deepcopy(b.settings)
            for conflict in ("output", "nested-output", "active-profile", "fallback-profile", "gemini-profile"):
                with self.subTest(first=first, second=second, conflict=conflict):
                    b.settings = deepcopy(saved)
                    if conflict in {"output", "nested-output"}:
                        b.settings["download_folder"] = a.settings["download_folder"]
                        if conflict == "nested-output":
                            b.settings["download_folder"] = str(Path(a.settings["download_folder"]) / "nested")
                    elif conflict == "active-profile":
                        b.settings["profile_dir"] = a.settings["profile_dir"]
                    elif conflict == "fallback-profile":
                        b.settings["chatgpt_accounts"].append(dict(a.settings["chatgpt_accounts"][0], id="borrowed"))
                    else:
                        b.settings["gemini_profile_dir"] = a.settings["gemini_profile_dir"]
                    result = self.bridge.start_batch("main", second)
                    self.assertFalse(result["ok"], result)
                    self.assertIn(first, result["error"])
                    self.assertIn(second, result["error"])
                    self.assertEqual(self.factories[second].calls, [])
            b.settings = saved

    def test_controls_and_log_exports_target_each_of_four_books(self):
        for key, api in self.manager.sessions.items():
            self.assertTrue(self.bridge.start_batch("main", key)["ok"])
            api.controller.append_log(f"ONLY {key}\n")
        processes = {key: api.controller.process for key, api in self.manager.sessions.items()}
        for key, api in self.manager.sessions.items():
            with self.subTest(key=key):
                others = {other: list(item.controller.log_history)
                          for other, item in self.manager.sessions.items() if other != key}
                self.assertTrue(self.bridge.continue_manual_intervention(key)["ok"])
                self.assertEqual(processes[key].stdin.writes, ["\n"])
                result = self.bridge.export_log(key)
                self.assertTrue(result["ok"], result)
                self.assertEqual(Path(result["data"]["path"]).parent, Path(api.settings["download_folder"]))
                self.assertIn(f"ONLY {key}", Path(result["data"]["path"]).read_text(encoding="utf-8"))
                with patch.object(api, "_copy_text") as copy:
                    self.assertTrue(self.bridge.copy_log(key)["ok"])
                    copy.assert_called_once_with("".join(api.controller.log_history))
                self.stopped.clear()
                self.assertTrue(self.bridge.stop_process(key)["ok"])
                self.assertEqual(self.stopped, [processes[key]])
                self.assertTrue(self.bridge.clear_log(key)["ok"])
                for other, log in others.items():
                    item = self.manager.sessions[other]
                    self.assertIs(item.controller.process, processes[other])
                    self.assertTrue(item.controller.is_running())
                    self.assertEqual(item.controller.log_history, log)

    def test_four_fallbacks_and_auto_next_keep_their_sessions(self):
        accounts = {}
        for key, api in self.manager.sessions.items():
            self.assertTrue(self.bridge.add_account(f"Fallback {key}", key)["ok"])
            accounts[key] = api.settings["chatgpt_accounts"][-1]
            api.controller.schedule_auto_next()
        for key, api in self.manager.sessions.items():
            with self.subTest(key=key):
                others = {other: item.controller.state.auto_next_active
                          for other, item in self.manager.sessions.items() if other != key}
                api.controller.handle_worker_output('__ACCOUNT_EVENT__=' + json.dumps(
                    {"event": "account_switched", "account_id": accounts[key]["id"]}))
                api._dispatch_once()
                self.assertTrue(self.bridge.run_auto_next_now(key)["ok"])
                env = self.factories[key].calls[-1][1]["env"]
                self.assertEqual(env["PROFILE_DIR"], accounts[key]["profile_dir"])
                self.assertEqual(env.get("BATCH_TRANSLATOR_WORKER_VARIANT"), "books34" if key in {"book-3", "book-4"} else None)
                snapshot = json.loads(Path(env["BATCH_TRANSLATOR_SETTINGS_FILE"]).read_text(encoding="utf-8"))
                self.assertEqual(snapshot["active_chatgpt_account_id"], accounts[key]["id"])
                self.assertTrue(all(event["session_id"] == key for event in api.sent_events))
                for other, active in others.items():
                    self.assertEqual(self.manager.sessions[other].controller.state.auto_next_active, active)

    def test_cancel_one_timer_and_preferences_preserve_other_timers(self):
        for api in self.manager.sessions.values():
            api.controller.schedule_auto_next()
        self.assertTrue(self.bridge.cancel_auto_next("book-3")["ok"])
        self.assertTrue(self.bridge.set_theme("dark")["ok"])
        self.assertTrue(self.bridge.set_language("en")["ok"])
        for key, api in self.manager.sessions.items():
            self.assertEqual(api.controller.state.auto_next_active, key != "book-3")
            self.assertEqual(api.settings["theme"], "dark")
            self.assertEqual(api.settings["language"], "en")

    def test_retry_force_and_login_use_each_books_snapshot(self):
        for key, api in self.manager.sessions.items():
            api.settings["start_from"] = "1_1.jpg"
            for mode in ("retry", "force", "login"):
                with self.subTest(key=key, mode=mode):
                    before = {other: len(factory.calls) for other, factory in self.factories.items()}
                    result = (self.bridge.login_account("default", key) if mode == "login"
                              else self.bridge.start_batch(mode, key))
                    self.assertTrue(result["ok"], result)
                    env = self.factories[key].calls[-1][1]["env"]
                    self.assertEqual(env["RUN_MODE"], mode)
                    self.assertEqual(env.get("BATCH_TRANSLATOR_WORKER_VARIANT"), "books34" if key in {"book-3", "book-4"} else None)
                    self.assertEqual(env["DOWNLOAD_FOLDER"], api.settings["download_folder"])
                    self.assertEqual(env["PROFILE_DIR"], api.settings["profile_dir"])
                    for other, count in before.items():
                        self.assertEqual(len(self.factories[other].calls), count + (other == key))
                    api.controller.process.return_code = 0
                    api.controller.handle_process_done(0)
                    api._dispatch_once()
                    api.controller.cancel_auto_next()

    def test_new_books_alone_trigger_close_confirmation(self):
        window = Mock()
        window.create_confirmation_dialog.return_value = False
        self.manager._attach_window(window)
        self.assertTrue(self.manager._confirm_close())
        for key in ("book-3", "book-4"):
            api = self.manager.sessions[key]
            for field in ("running", "auto_next_active"):
                with self.subTest(key=key, field=field):
                    setattr(api.controller.state, field, True)
                    self.assertFalse(self.manager._confirm_close())
                    window.create_confirmation_dialog.assert_called()
                    setattr(api.controller.state, field, False)
        self.assertTrue(self.manager._confirm_close())

    def test_shutdown_stops_all_four_and_closes_their_schedulers(self):
        for key, api in self.manager.sessions.items():
            self.assertTrue(self.bridge.start_batch("main", key)["ok"])
            api.controller.schedule_auto_next()
        processes = [api.controller.process for api in self.manager.sessions.values()]
        self.manager._shutdown()
        self.assertEqual(self.stopped, processes)
        for api in self.manager.sessions.values():
            self.assertTrue(api.scheduler.closed)
            self.assertTrue(api._stop_dispatcher.is_set())
            self.assertFalse(api.controller.state.auto_next_active)
        self.assertFalse(self.bridge.start_batch("main", "book-4")["ok"])


if __name__ == "__main__":
    unittest.main()
