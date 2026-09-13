import csv
import importlib.util
import json
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

playwright_module = types.ModuleType("playwright")
playwright_sync_module = types.ModuleType("playwright.sync_api")
playwright_sync_module.sync_playwright = lambda: None
try:
    import playwright.sync_api
except ImportError:
    sys.modules.setdefault("playwright", playwright_module)
    sys.modules.setdefault("playwright.sync_api", playwright_sync_module)

worker_spec = importlib.util.spec_from_file_location(
    "worker_under_test", PROJECT_ROOT / "run_chatgpt_batch.py"
)
worker = importlib.util.module_from_spec(worker_spec)
worker_spec.loader.exec_module(worker)
app_namespace = runpy.run_path(str(PROJECT_ROOT / "app.pyw"), run_name="app_under_test")
App = app_namespace["ChatGPTBatchApp"]


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self):
        self.state = None

    def config(self, **kwargs):
        self.state = kwargs.get("state", self.state)


class Clock:
    def __init__(self):
        self.now = 0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class BatchSelectionTests(unittest.TestCase):
    def setUp(self):
        self.images = [
            Path("01_101.jpg"),
            Path("02_102.jpg"),
            Path("03_103.jpg"),
            Path("03_104.jpg"),
        ]

    def test_force_mode_runs_exactly_one_matched_file(self):
        with patch.object(worker, "START_FROM", "02_102.jpg"), patch.object(worker, "RUN_MODE", "force"), patch.object(worker, "BATCH_SIZE", 5), patch.object(worker, "read_latest_status", return_value={}):
            selected = worker.apply_start_from(self.images, require_single_match=True)
            self.assertEqual([path.name for path in worker.get_next_batch(selected)], ["02_102.jpg"])

    def test_missing_or_ambiguous_force_target_stops(self):
        with patch.object(worker, "START_FROM", "missing.jpg"):
            with self.assertRaises(ValueError):
                worker.apply_start_from(self.images, require_single_match=True)

        with patch.object(worker, "START_FROM", "3"):
            with self.assertRaises(ValueError):
                worker.apply_start_from(self.images, require_single_match=True)

    def test_output_name_is_unique_for_same_page(self):
        self.assertNotEqual(
            worker.get_output_name(Path("73_129.jpg")),
            worker.get_output_name(Path("73_130.jpg")),
        )

    def test_batch_result_marker_is_single_line_json(self):
        result = {"selected_count": 10, "success_count": 10, "failure_count": 0}
        with patch.object(worker, "print") as mock_print:
            worker.emit_batch_result(result)

        emitted = mock_print.call_args.args[0]
        self.assertTrue(emitted.startswith(worker.BATCH_RESULT_PREFIX))
        self.assertEqual(
            json.loads(emitted[len(worker.BATCH_RESULT_PREFIX):]),
            result,
        )


class ProgressTests(unittest.TestCase):
    def test_job_reconciles_outputs_and_errors_and_stops_without_progress(self):
        images = [Path("1_1.jpg"), Path("2_2.jpg"), Path("3_3.jpg")]
        with patch.object(worker, "read_latest_status", return_value={
            "1_1.jpg": {"status": "done"}, "2_2.jpg": {"status": "fail"}
        }), patch.object(worker, "output_file_exists", return_value=False), patch.object(worker, "legacy_output_file_exists", return_value=False):
            job = worker.get_job_state(images)
            self.assertEqual((job["done"], job["failed"], job["pending"]), (0, 1, 2))
            self.assertEqual(job["state"], "pending")
            result = {"mode": "main", "selected_count": 2, "pending_before": 2}
            with patch.object(worker, "print"):
                self.assertEqual(worker.finish_batch_result(result, images), 3)
            with patch.object(worker, "output_file_exists", side_effect=lambda img: img.name != "2_2.jpg"):
                with patch.object(worker, "print"):
                    self.assertEqual(worker.finish_batch_result(result, images), 2)
                self.assertEqual(result["job"]["state"], "needs_retry")
            with patch.object(worker, "output_file_exists", return_value=True):
                with patch.object(worker, "print"):
                    self.assertEqual(worker.finish_batch_result(result, images), 0)
                self.assertEqual(result["job"]["state"], "complete")

    def test_empty_job_completes_without_opening_browser(self):
        with patch.object(worker, "ensure_dirs"), patch.object(worker, "init_progress"), patch.object(worker, "get_images", return_value=[]), patch.object(worker, "START_FROM", ""), patch.object(worker, "RUN_MODE", "main"), patch.object(worker, "read_latest_status", return_value={}), patch.object(worker, "sync_playwright") as browser, patch.object(worker, "print"):
            self.assertEqual(worker.main(), 0)
            browser.assert_not_called()

    def test_done_with_missing_output_returns_to_main_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            image = Path("73_129.jpg")
            with patch.object(worker, "DOWNLOAD_FOLDER", str(output)), patch.object(worker, "PROGRESS_FILE", str(output / "progress.csv")), patch.object(worker, "RUN_MODE", "main"), patch.object(worker, "BATCH_SIZE", 5):
                worker.write_progress(1, image.name, worker.get_output_name(image), "done", "OK")
                self.assertEqual(worker.get_next_batch([image]), [image])

                Image.new("RGB", (100, 100)).save(output / worker.get_output_name(image))
                self.assertEqual(worker.get_next_batch([image]), [])

    def test_unambiguous_legacy_done_output_is_not_reprocessed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            image = Path("73_129.jpg")
            with patch.object(worker, "DOWNLOAD_FOLDER", str(output)), patch.object(worker, "PROGRESS_FILE", str(output / "progress.csv")), patch.object(worker, "RUN_MODE", "main"), patch.object(worker, "BATCH_SIZE", 5):
                worker.write_progress(1, image.name, "00073VN.png", "done", "OK")
                Image.new("RGB", (100, 100)).save(output / "00073VN.png")
                self.assertEqual(worker.get_next_batch([image]), [])

    def test_only_latest_failure_is_exported(self):
        from progress_utils import latest_failed_rows

        with tempfile.TemporaryDirectory() as directory:
            progress = Path(directory) / "progress.csv"
            with progress.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["file", "status"])
                writer.writeheader()
                writer.writerow({"file": "recovered.jpg", "status": "fail"})
                writer.writerow({"file": "recovered.jpg", "status": "done"})
                writer.writerow({"file": "still_failed.jpg", "status": "error"})

            self.assertEqual(
                [row["file"] for row in latest_failed_rows(progress)],
                ["still_failed.jpg"],
            )


class CompletionTests(unittest.TestCase):
    def test_idle_page_without_new_response_is_not_success(self):
        clock = Clock()
        before = {"count": 0, "last_len": 0, "last_tail": ""}
        with patch.object(worker, "time", clock), patch.object(worker, "sleep", clock.sleep), patch.object(worker, "wait_if_cloudflare"), patch.object(worker, "is_generating", return_value=False), patch.object(worker, "has_new_assistant_response", return_value=False), patch.object(worker, "get_prompt_text", return_value=""):
            self.assertFalse(
                worker.wait_response_after_send(
                    None,
                    timeout_start=3,
                    timeout_done=10,
                    resend_text="prompt",
                    before_signature=before,
                )
            )

    def test_new_image_waits_until_generation_has_stopped_and_stabilized(self):
        clock = Clock()
        generating = iter([True, False, False])
        with patch.object(worker, "time", clock), patch.object(worker, "sleep", clock.sleep), patch.object(worker, "wait_if_cloudflare"), patch.object(worker, "get_latest_new_image", return_value="https://example.test/output.png"), patch.object(worker, "is_generating", side_effect=lambda _: next(generating, False)), patch.object(worker, "has_clear_generation_error", return_value=False):
            self.assertEqual(
                worker.wait_image_generation_finished_or_image_ready(None, [], timeout=25),
                "https://example.test/output.png",
            )


class ApplicationStateTests(unittest.TestCase):
    def make_app(self):
        app = App.__new__(App)
        app.settings = app_namespace["DEFAULT_SETTINGS"].copy()
        app.image_var = Variable("new-input")
        app.output_var = Variable("new-output")
        app.profile_var = Variable("new-profile")
        app.batch_var = Variable("2")
        app.start_from_var = Variable("02_102.jpg")
        app.service_var = Variable("Google Gemini")
        app.manual_action_required = False
        app.status_var = Variable("")
        app.continue_btn = Widget()
        app.auto_next_var = Variable(True)
        app.auto_next_delay_var = Variable("2")
        app.current_run_mode = "main"
        app.current_run_intervened = False
        app.current_batch_result = None
        return app

    def test_save_settings_updates_in_memory_values(self):
        app = self.make_app()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            App.save_settings.__globals__, {"SETTINGS_FILE": Path(directory) / "settings.json"}
        ):
            app.save_settings()
        self.assertEqual(app.settings["image_folder"], "new-input")
        self.assertEqual(app.settings["service"], "gemini")

    def test_manual_action_state_survives_widget_rebuild(self):
        app = self.make_app()
        app.update_manual_button_from_log("MANUAL_ACTION_REQUIRED")
        self.assertTrue(app.manual_action_required)
        self.assertEqual(app.continue_btn.state, "normal")

    def test_auto_next_requires_a_full_successful_main_batch(self):
        app = self.make_app()
        app.current_batch_result = {
            "requested_batch_size": 10,
            "selected_count": 10,
            "completed_count": 10,
            "success_count": 10,
            "failure_count": 0,
            "next_pending_count": 1,
        }

        self.assertEqual(app.get_auto_next_skip_reason(0), ("", {}))

        app.current_batch_result["failure_count"] = 1
        app.current_batch_result["success_count"] = 9
        self.assertEqual(app.get_auto_next_skip_reason(0)[0], "auto_skip_failed")

        app.current_batch_result.update({
            "selected_count": 9,
            "completed_count": 9,
            "success_count": 9,
            "failure_count": 0,
        })
        self.assertEqual(app.get_auto_next_skip_reason(0)[0], "auto_skip_incomplete")

    def test_auto_next_does_not_run_after_manual_intervention_or_worker_failure(self):
        app = self.make_app()
        app.current_batch_result = {
            "requested_batch_size": 10,
            "selected_count": 10,
            "completed_count": 10,
            "success_count": 10,
            "failure_count": 0,
            "next_pending_count": 1,
        }

        app.current_run_intervened = True
        self.assertEqual(app.get_auto_next_skip_reason(0)[0], "auto_skip_intervened")

        app.current_run_intervened = False
        self.assertEqual(app.get_auto_next_skip_reason(1)[0], "auto_skip_process_error")

    def test_auto_next_delay_must_be_a_finite_positive_number(self):
        app = self.make_app()
        self.assertEqual(app.get_auto_next_delay_seconds(), 120)

        for value in ("0", "-1", "nan", "inf", "not a number"):
            app.auto_next_delay_var.set(value)
            with self.assertRaises(ValueError):
                app.get_auto_next_delay_seconds()


if __name__ == "__main__":
    unittest.main()
