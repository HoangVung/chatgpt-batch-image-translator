import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop.workflow_sessions import SessionManager, WORKFLOW_IDS


class AsyncFolderProgressTests(unittest.TestCase):
    def test_blocked_drive_does_not_block_startup_other_tab_or_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(data_dir=Path(directory))
            first = manager.sessions["book-1"]
            entered, release, returned = threading.Event(), threading.Event(), threading.Event()
            result = {}

            def slow_read(settings):
                entered.set()
                release.wait(5)
                return {"done": 7, "total": 20}

            def initialize():
                result.update(manager._invoke("get_initial_state"))
                returned.set()

            with patch.object(first._folder_progress, "read", side_effect=slow_read):
                caller = threading.Thread(target=initialize, daemon=True)
                caller.start()
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertTrue(returned.wait(1), "startup is waiting on the drive")
                    data = result["data"]
                    self.assertEqual(tuple(data["sessions"]), WORKFLOW_IDS)
                    self.assertEqual(data["settings"]["language"], "vi")
                    self.assertEqual(data["controller"]["folder_progress"], {"done": None, "total": None})
                    for key in WORKFLOW_IDS[1:]:
                        self.assertTrue(manager._invoke("get_initial_state", session_id=key)["ok"])
                    scan = first._folder_progress_thread
                    # Repeated snapshots must not create extra blocked scans.
                    manager._invoke("get_initial_state")
                    self.assertIs(first._folder_progress_thread, scan)
                    manager._shutdown()
                    self.assertTrue(scan.is_alive())
                    events_before = len(first.sent_events)
                finally:
                    release.set()
                    caller.join(2)
                    if first._folder_progress_thread:
                        first._folder_progress_thread.join(2)
                    manager._shutdown()
                self.assertEqual(len(first.sent_events), events_before)

    def test_old_scan_is_discarded_and_latest_folder_is_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(data_dir=Path(directory))
            api = manager.sessions["book-1"]
            entered, release, published = threading.Event(), threading.Event(), threading.Event()
            calls = []
            original_push = api._push_event

            def read(settings):
                calls.append(settings["image_folder"])
                if len(calls) == 1:
                    entered.set()
                    release.wait(5)
                    return {"done": 99, "total": 100}
                return {"done": 2, "total": 3}

            def push(kind, payload):
                event = original_push(kind, payload)
                if kind == "folder_progress_changed":
                    published.set()
                return event

            with patch.object(api._folder_progress, "read", side_effect=read), patch.object(api, "_push_event", side_effect=push):
                try:
                    api.get_initial_state()
                    self.assertTrue(entered.wait(2))
                    for name in ("middle", "latest"):
                        self.assertTrue(api.save_settings({"image_folder": str(Path(directory) / name)})["ok"])
                    release.set()
                    self.assertTrue(published.wait(2))
                    self.assertEqual(len(calls), 2)
                    self.assertTrue(calls[-1].endswith("latest"))
                    counts = [e["payload"] for e in api.sent_events if e["type"] == "folder_progress_changed"]
                    self.assertEqual(counts, [{"done": 2, "total": 3}])
                    self.assertEqual(api.get_initial_state()["data"]["controller"]["folder_progress"], counts[0])
                finally:
                    release.set()
                    manager._shutdown()

    def test_scan_error_keeps_settings_available_and_can_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(data_dir=Path(directory))
            api = manager.sessions["book-1"]
            try:
                with patch.object(api._folder_progress, "read", side_effect=OSError("Drive offline")):
                    self.assertTrue(api.get_initial_state()["ok"])
                    thread = api._folder_progress_thread
                    if thread:
                        thread.join(2)
                    self.assertEqual(api._folder_progress_value, {"done": None, "total": None})
                with patch.object(api._folder_progress, "read", return_value={"done": 1, "total": 2}):
                    api._request_folder_progress(refresh=True)
                    thread = api._folder_progress_thread
                    if thread:
                        thread.join(2)
                    self.assertEqual(api._folder_progress_value, {"done": 1, "total": 2})
            finally:
                manager._shutdown()
