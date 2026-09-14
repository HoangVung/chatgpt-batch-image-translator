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
make_touch_scroll_handlers = app_namespace["make_touch_scroll_handlers"]


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

    def test_completed_batch_is_recorded_before_browser_context_closes(self):
        class Context:
            pages = [object()]

            def close(self):
                pass

        class PlaywrightScope:
            def __enter__(self):
                return object()

            def __exit__(self, *_args):
                return False

        image = Path("01_101.jpg")
        events = []
        job = {
            "total": 2,
            "done": 1,
            "failed": 0,
            "pending": 1,
            "pending_files": [Path("02_102.jpg")],
            "state": "pending",
        }
        with patch.object(worker, "ensure_dirs"), \
             patch.object(worker, "init_progress"), \
             patch.object(worker, "get_images", return_value=[image]), \
             patch.object(worker, "get_next_batch", return_value=[image]), \
             patch.object(worker, "get_job_state", return_value=job), \
             patch.object(worker, "get_chatgpt_accounts", return_value=[]), \
             patch.object(worker, "launch_persistent_context", return_value=Context()), \
             patch.object(worker, "minimize_own_browser"), \
             patch.object(worker, "login_if_needed"), \
             patch.object(worker, "process_one"), \
             patch.object(worker, "write_job_checkpoint"), \
             patch.object(worker, "finish_batch_result", side_effect=lambda *_: events.append("result") or 0), \
             patch.object(worker, "close_browser_context", side_effect=lambda *_: events.append("close")), \
             patch.object(worker, "sync_playwright", return_value=PlaywrightScope()), \
             patch.object(worker, "print"):
            self.assertEqual(worker.main(), 0)

        self.assertEqual(events, ["result", "close"])

    def test_login_mode_opens_only_the_account_session(self):
        with patch.object(worker, "RUN_MODE", "login"), patch.object(worker, "login_only", return_value=0) as login_only, patch.object(worker, "get_images", side_effect=AssertionError("batch images should not be read")):
            self.assertEqual(worker.main(), 0)
            login_only.assert_called_once_with()

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

    def test_legacy_chatgpt_profile_becomes_the_first_managed_account(self):
        app = self.make_app()
        app.settings.update({
            "service": "chatgpt",
            "profile_dir": "legacy-business-profile",
            "chatgpt_accounts": [],
            "active_chatgpt_account_id": "",
        })

        account = app.get_active_chatgpt_account()

        self.assertEqual(account["profile_dir"], "legacy-business-profile")
        self.assertEqual(app.settings["active_chatgpt_account_id"], account["id"])

    def test_loading_legacy_settings_keeps_a_custom_chatgpt_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_file = Path(directory) / "settings.json"
            settings_file.write_text(
                json.dumps({"service": "chatgpt", "profile_dir": "legacy-business-profile"}),
                encoding="utf-8",
            )
            app = App.__new__(App)
            with patch.dict(App.load_settings.__globals__, {"SETTINGS_FILE": settings_file}):
                app.settings = app.load_settings()

        self.assertEqual(app.get_active_chatgpt_account()["profile_dir"], "legacy-business-profile")

    def test_selecting_a_managed_account_updates_the_profile_for_the_next_run(self):
        app = self.make_app()
        app.settings.update({
            "chatgpt_accounts": [
                {"id": "one", "name": "Business 1", "profile_dir": "profile-one"},
                {"id": "two", "name": "Business 2", "profile_dir": "profile-two"},
            ],
            "active_chatgpt_account_id": "one",
        })
        app.account_var = Variable("Business 2")
        with patch.object(app, "save_settings"):
            app.select_chatgpt_account("Business 2")

        self.assertEqual(app.settings["active_chatgpt_account_id"], "two")
        self.assertEqual(app.profile_var.get(), "profile-two")

    def test_account_name_dialog_prefills_and_selects_the_current_name(self):
        app = self.make_app()

        class Entry:
            def __init__(self):
                self.inserted = None
                self.selection = None

            def insert(self, index, value):
                self.inserted = (index, value)

            def select_range(self, start, end):
                self.selection = (start, end)

        class Dialog:
            def __init__(self):
                self._entry = Entry()

            def after(self, _delay, callback):
                callback()

            def get_input(self):
                return "  Đăng nhập chính  "

        dialog = Dialog()
        with patch.object(app_namespace["ctk"], "CTkInputDialog", return_value=dialog):
            self.assertEqual(app.prompt_chatgpt_account_name("ChatGPT 1"), "Đăng nhập chính")

        self.assertEqual(dialog._entry.inserted, (0, "ChatGPT 1"))
        self.assertEqual(dialog._entry.selection, (0, "end"))

    def test_renaming_active_account_updates_the_saved_label(self):
        app = self.make_app()
        app.settings.update({
            "chatgpt_accounts": [
                {"id": "one", "name": "ChatGPT 1", "profile_dir": "profile-one"},
            ],
            "active_chatgpt_account_id": "one",
        })

        with patch.object(app, "can_change_chatgpt_account", return_value=True), \
             patch.object(app, "prompt_chatgpt_account_name", return_value="Business chính"), \
             patch.object(app, "save_settings"):
            app.rename_chatgpt_account()

        self.assertEqual(app.settings["chatgpt_accounts"][0]["name"], "Business chính")
        self.assertEqual(app.status_var.get(), 'Đã đổi tên thành "Business chính".')

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

    def test_auto_next_recovers_only_after_a_verified_successful_result(self):
        app = self.make_app()
        app.current_batch_result = {
            "requested_batch_size": 10,
            "selected_count": 10,
            "completed_count": 10,
            "success_count": 10,
            "failure_count": 0,
            "next_pending_count": 1,
            "exit_code": 0,
        }

        self.assertEqual(
            app.get_auto_next_skip_reason(-1),
            ("", {"recovered_exit_code": -1}),
        )

        app.current_batch_result["exit_code"] = 2
        self.assertEqual(app.get_auto_next_skip_reason(-1)[0], "auto_skip_process_error")

    def test_auto_next_delay_must_be_a_finite_positive_number(self):
        app = self.make_app()
        self.assertEqual(app.get_auto_next_delay_seconds(), 120)

        for value in ("0", "-1", "nan", "inf", "not a number"):
            app.auto_next_delay_var.set(value)
            with self.assertRaises(ValueError):
                app.get_auto_next_delay_seconds()


class UiStyleTests(unittest.TestCase):
    def make_app(self, style="golden_gate", theme="light"):
        app = App.__new__(App)
        app.settings = app_namespace["DEFAULT_SETTINGS"].copy()
        app.settings.update({"ui_style": style, "theme": theme})
        return app

    def test_golden_gate_palette_has_all_widget_colors(self):
        app = self.make_app()
        palette = app.get_palette()
        required = {
            "app_bg", "chrome_bg", "card_bg", "input_bg", "log_bg", "text",
            "muted", "field", "border", "gray_btn", "gray_btn_active",
            "gray_btn_pressed", "scroll_track", "scroll_thumb", "scroll_arrow",
            "selection", "accent", "accent_hover", "accent_pressed", "accent_text",
            "danger", "danger_hover", "danger_pressed", "disabled_bg", "disabled_text"
        }
        self.assertTrue(required.issubset(palette))
        self.assertEqual(app.style_code(), "golden_gate")
        classic = self.make_app(style="classic").get_palette()
        self.assertNotEqual(palette["app_bg"], classic["app_bg"])

    def test_style_change_does_not_cancel_auto_next_or_replace_worker(self):
        app = self.make_app(style="classic")
        class Frame:
            def __init__(self):
                self.visible = False

            def grid(self):
                self.visible = True

            def grid_remove(self):
                self.visible = False

        class Canvas:
            def __init__(self):
                self.position = None

            def yview(self):
                return (0.25, 0.5)

            def yview_moveto(self, position):
                self.position = position

        app.root = types.SimpleNamespace(winfo_children=lambda: [])
        app.proc = object()
        app.auto_next_deadline = 123
        app.auto_next_after_id = "timer-id"
        app.log_history = ["existing log"]
        app.status_var = Variable("Waiting for next batch")
        app.progress_var = Variable(65)
        app.progress_label = Variable("Progress: 6/10 images (65%)")
        app.auto_next_countdown_var = Variable("Next batch in 00:30")
        app.main_canvas = Canvas()

        def rebuild_widgets():
            app.status_var = Variable("")
            app.progress_var = Variable(0)
            app.progress_label = Variable("")
            app.auto_next_countdown_var = Variable("")
            app.auto_next_frame = Frame()
            app.main_canvas = Canvas()

        with patch.object(app, "cancel_auto_next", side_effect=AssertionError("style change cancelled timer")), \
             patch.object(app, "save_settings"), \
             patch.object(app, "setup_style"), \
             patch.object(app, "build_ui", side_effect=rebuild_widgets):
            app.set_style("golden_gate")

        self.assertEqual(app.style_code(), "golden_gate")
        self.assertIsNotNone(app.proc)
        self.assertEqual(app.auto_next_deadline, 123)
        self.assertEqual(app.auto_next_after_id, "timer-id")
        self.assertEqual(app.status_var.get(), "Waiting for next batch")
        self.assertEqual(app.progress_var.get(), 65)
        self.assertEqual(app.progress_label.get(), "Progress: 6/10 images (65%)")
        self.assertEqual(app.auto_next_countdown_var.get(), "Next batch in 00:30")
        self.assertTrue(app.auto_next_frame.visible)
        self.assertEqual(app.main_canvas.position, 0.25)


class ScrollableLayoutTests(unittest.TestCase):
    def test_tall_content_keeps_its_full_canvas_height(self):
        content_height, log_can_expand = App.get_scrollable_main_layout(1400, 700)

        self.assertEqual(content_height, 1400)
        self.assertFalse(log_can_expand)

    def test_short_content_fills_the_viewport_for_the_log_card(self):
        content_height, log_can_expand = App.get_scrollable_main_layout(500, 700)

        self.assertEqual(content_height, 700)
        self.assertTrue(log_can_expand)


class TouchScrollTests(unittest.TestCase):
    class Target:
        def __init__(self):
            self.calls = []

        def yview_scroll(self, amount, mode):
            self.calls.append((amount, mode))

    class Event:
        def __init__(self, y_root):
            self.y_root = y_root

    def test_log_touch_blocks_text_selection_for_the_entire_gesture(self):
        target = self.Target()
        press, move, release = make_touch_scroll_handlers(
            target,
            prevent_drag_selection=True,
            prefer_pixel_scroll=True,
        )

        self.assertEqual(press(self.Event(100)), "break")
        self.assertEqual(move(self.Event(101)), "break")
        self.assertEqual(move(self.Event(80)), "break")
        self.assertEqual(release(self.Event(80)), "break")
        self.assertEqual(target.calls, [(-1, "pixels"), (21, "pixels")])

    def test_log_touch_blocks_orphan_motion_and_release_events(self):
        target = self.Target()
        _, move, release = make_touch_scroll_handlers(
            target,
            prevent_drag_selection=True,
        )

        self.assertEqual(move(self.Event(50)), "break")
        self.assertEqual(release(self.Event(50)), "break")
        self.assertEqual(target.calls, [])


if __name__ == "__main__":
    unittest.main()
