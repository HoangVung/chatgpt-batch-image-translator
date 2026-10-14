"""Business/Personal quota regression through the worker and Studio bridge."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from desktop.quota_limits import QuotaLimits
from desktop.web_api import WebApi


class QuotaAccountSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.apis = []
        self.now = [100000]
        self.accounts = [
            {"id": "business", "name": "Vung-Business", "profile_dir": str(self.root / "business")},
            {"id": "personal", "name": "Vung-Personal", "profile_dir": str(self.root / "personal")},
        ]
        self.api = self.make_api()
        self.api.settings.update(chatgpt_accounts=self.accounts,
                                 active_chatgpt_account_id="business",
                                 download_folder=str(self.root / "output"))

    def make_api(self):
        api = WebApi(app_dir=Path(__file__).resolve().parents[1], data_dir=self.root)
        api._quota_limits.clock = lambda: self.now[0]
        self.apis.append(api)
        return api

    def tearDown(self):
        for api in self.apis:
            api._shutdown()
        self.temp.cleanup()

    def emit(self, event, **data):
        self.api.controller.handle_worker_output("__ACCOUNT_EVENT__=" + json.dumps(
            {"event": event, **data}) + "\n")
        self.api._dispatch_once()

    def exhaust_both(self):
        self.emit("account_quota_exhausted", account_id="business", account_name="Vung-Business",
                  detected_at=100000, evidence="The limit resets in 6 minutes.")
        self.emit("account_switched", account_id="personal", account_name="Vung-Personal",
                  image="301_301.jpg")
        self.emit("account_quota_exhausted", account_id="personal", account_name="Vung-Personal",
                  detected_at=100001, evidence="The limit resets in 12 hours.")

    def test_both_limits_survive_switch_reset_estimate_and_restart(self):
        self.exhaust_both()
        self.assertEqual(self.api.settings["active_chatgpt_account_id"], "personal")
        self.now[0] = 100361
        self.api._dispatch_once()
        rows = {row["account_id"]: row for row in self.api._snapshot()["quota_limits"]}
        self.assertEqual(set(rows), {"business", "personal"})
        self.assertEqual(rows["business"]["reset_at"], 100360)
        self.assertTrue(rows["business"]["estimate_due"])
        self.assertEqual(rows["personal"]["reset_at"], 143201)
        self.assertFalse(rows["personal"]["estimate_due"])
        restored = self.make_api().get_initial_state()["data"]["controller"]["quota_limits"]
        self.assertEqual(restored, list(rows.values()))

    def test_current_and_last_attempted_are_separate_and_restore_from_existing_checkpoint(self):
        self.exhaust_both()
        output = self.root / "output"
        output.mkdir()
        checkpoint = output / "job_checkpoint.json"
        checkpoint.write_text(json.dumps({"version": 1, "state": "waiting_quota",
            "current_image": "301_301.jpg", "active_account": self.accounts[1],
            "account_states": {a["id"]: {"state": "quota_exhausted"} for a in self.accounts}}))
        before = checkpoint.read_bytes()
        selected = self.api.select_account("business")
        self.assertTrue(selected["ok"])
        self.assertEqual(self.api._snapshot()["last_attempted_account"]["id"], "personal")
        restored = self.make_api().get_initial_state()["data"]
        self.assertEqual(restored["settings"]["active_chatgpt_account_id"], "business")
        self.assertEqual(restored["controller"]["last_attempted_account"],
                         {"id": "personal", "name": "Vung-Personal"})
        self.assertEqual(len(restored["controller"]["quota_limits"]), 2)
        self.assertEqual(checkpoint.read_bytes(), before)

    def test_starting_checkpoint_does_not_claim_an_account_was_attempted(self):
        output = self.root / "output"
        output.mkdir()
        (output / "job_checkpoint.json").write_text(json.dumps({"version": 1,
            "stage": "starting", "active_account": self.accounts[0]}))
        self.assertIsNone(self.api._snapshot()["last_attempted_account"])
        self.assertEqual(self.api.settings["active_chatgpt_account_id"], "business")

    def test_confirmed_recovery_updates_only_its_account_after_estimate(self):
        self.exhaust_both()
        self.now[0] = 100361
        self.emit("account_image_created", account_id="personal", account_name="Vung-Personal",
                  image="301_301.jpg")
        rows = self.api._snapshot()["quota_limits"]
        self.assertEqual([row["account_id"] for row in rows], ["business"])
        self.assertTrue(rows[0]["estimate_due"])
        self.assertEqual(QuotaLimits(self.root / "quota_limits.json").snapshot()[0]["account_id"], "business")

    def test_both_workers_retry_image_301_and_keep_300_done_with_exit_4(self):
        import run_chatgpt_batch as stable
        import run_chatgpt_batch_books34 as isolated

        class Context:
            def __init__(self, page):
                self.pages = [page]
            def close(self):
                pass

        class Scope:
            def __enter__(self):
                return object()
            def __exit__(self, *_args):
                return False

        images = [Path(f"{i:03}_{i:03}.jpg") for i in range(1, 302)]
        job = {"done": 300, "total": 301, "failed": 0, "pending": 1,
               "pending_files": images[-1:], "state": "pending"}
        for worker in (stable, isolated):
            with self.subTest(worker=worker.__name__), ExitStack() as stack:
                first, second = object(), object()
                output = self.root / worker.__name__
                patches = {
                    "RUN_MODE": "main", "SERVICE": "chatgpt", "BATCH_SIZE": 301,
                    "START_FROM": "", "DOWNLOAD_FOLDER": str(output),
                    "CFG": {"auto_account_fallback_enabled": True},
                }
                for name, value in patches.items():
                    stack.enter_context(patch.object(worker, name, value))
                for name in ("ensure_dirs", "init_progress", "minimize_own_browser", "print", "sleep"):
                    stack.enter_context(patch.object(worker, name))
                for name, value in {
                    "get_images": images, "get_next_batch": images[-1:], "get_job_state": job,
                    "get_chatgpt_accounts": self.accounts, "sync_playwright": Scope(),
                    "launch_persistent_context": Context(first), "login_if_needed": first,
                    "open_existing_chatgpt_account": (Context(second), second),
                }.items():
                    stack.enter_context(patch.object(worker, name, return_value=value))
                attempt = stack.enter_context(patch.object(worker, "process_one", side_effect=[
                    worker.QuotaExhaustedError("The limit resets in 6 minutes.", detected_at=100000),
                    worker.QuotaExhaustedError("The limit resets in 12 hours.", detected_at=100001),
                ]))
                progress = stack.enter_context(patch.object(worker, "write_progress"))
                result = stack.enter_context(patch.object(worker, "emit_batch_result"))
                stack.enter_context(patch.object(worker, "emit_account_event", side_effect=self.emit))
                self.assertEqual(worker.main(), 4)
                progress.assert_not_called()
                self.assertEqual([call.args[2].name for call in attempt.call_args_list],
                                 ["301_301.jpg", "301_301.jpg"])
                final = result.call_args.args[0]
                self.assertEqual(final["job"]["state"], "waiting_quota")
                self.assertEqual((final["job"]["done"], final["job"]["total"]), (300, 301))
                self.assertEqual(final["waiting_image"], "301_301.jpg")
                self.assertEqual(final["failure_count"], 0)
                checkpoint = json.loads((output / "job_checkpoint.json").read_text(encoding="utf-8"))
                self.assertEqual(checkpoint["current_image"], "301_301.jpg")
                self.assertEqual(checkpoint["active_account"]["id"], "personal")
                self.assertEqual({a["state"] for a in checkpoint["account_states"].values()},
                                 {"quota_exhausted"})
                self.assertEqual(set(checkpoint["account_states"]), {"business", "personal"})
                self.assertEqual(len(self.api._snapshot()["quota_limits"]), 2)


if __name__ == "__main__":
    unittest.main()
