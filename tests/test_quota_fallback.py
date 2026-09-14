import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]

playwright_module = types.ModuleType("playwright")
playwright_sync_module = types.ModuleType("playwright.sync_api")
playwright_sync_module.sync_playwright = lambda: None
sys.modules.setdefault("playwright", playwright_module)
sys.modules.setdefault("playwright.sync_api", playwright_sync_module)

worker_spec = importlib.util.spec_from_file_location(
    "worker_quota_under_test", PROJECT_ROOT / "run_chatgpt_batch.py"
)
worker = importlib.util.module_from_spec(worker_spec)
worker_spec.loader.exec_module(worker)


class BodyLocator:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text


class BodyOnlyPage:
    def __init__(self, text):
        self.text = text

    def evaluate(self, *_args, **_kwargs):
        raise RuntimeError("DOM snapshot unavailable in fixture")

    def locator(self, selector):
        return BodyLocator(self.text)


class QuotaDetectionTests(unittest.TestCase):
    def test_exact_vietnamese_quota_messages_are_detected(self):
        samples = [
            "Bạn đã hết lượt tạo hình ảnh&#x20;",
            "Bạn hiện đã hết lượt tạo ảnh.",
            "Bạn đã đạt giới hạn yêu cầu tạo ảnh của gói Plus.",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                marker = worker.find_image_quota_marker(sample)
                self.assertIsNotNone(marker)
                self.assertIsNotNone(
                    worker.get_generation_quota_evidence(BodyOnlyPage(sample))
                )

    def test_quota_detector_ignores_unrelated_companion_sentences(self):
        for sample in (
            "Hãy thử lại vào lúc 12:05.",
            "Bạn có thể tạo thêm hình ảnh sau khi giới hạn được đặt lại sau 1 giờ.",
            "Nâng cấp lên Pro",
            "Hiện tại tôi chưa thể gọi công cụ tạo ảnh để tạo hình con mèo cho bạn.",
        ):
            with self.subTest(sample=sample):
                self.assertIsNone(worker.find_image_quota_marker(sample))
                self.assertIsNone(
                    worker.get_generation_quota_evidence(BodyOnlyPage(sample))
                )

    def test_quota_event_requires_a_new_response_when_a_baseline_is_given(self):
        page = BodyOnlyPage("Bạn hiện đã hết lượt tạo ảnh.")
        before = {"count": 1, "last_len": 40, "last_tail": "previous response"}
        with patch.object(worker, "has_new_assistant_response", return_value=False):
            self.assertIsNone(worker.get_generation_quota_evidence(page, before))

    def test_old_quota_warning_in_history_does_not_trigger_for_later_response(self):
        class SnapshotPage:
            def evaluate(self, *_args, **_kwargs):
                return {
                    "assistant": [
                        "Bạn đã đạt giới hạn yêu cầu tạo ảnh của gói Plus.",
                        "Đây là phản hồi bình thường cho yêu cầu mới.",
                    ],
                    "notices": [],
                }

        before = {"count": 1, "last_len": 20, "last_tail": "old"}
        with patch.object(worker, "has_new_assistant_response", return_value=True):
            self.assertIsNone(worker.get_generation_quota_evidence(SnapshotPage(), before))

    def test_card_and_follow_up_paragraphs_in_one_new_response_are_scanned(self):
        class SnapshotPage:
            def evaluate(self, *_args, **_kwargs):
                return {
                    "assistant": [
                        "Bạn đã hết lượt tạo hình ảnh",
                        "Hiện tại tôi chưa thể gọi công cụ tạo ảnh cho bạn.",
                    ],
                    "notices": [],
                }

        before = {"count": 0, "last_len": 0, "last_tail": ""}
        with patch.object(worker, "has_new_assistant_response", return_value=True):
            self.assertIsNotNone(worker.get_generation_quota_evidence(SnapshotPage(), before))


class AccountRegistryTests(unittest.TestCase):
    def test_active_account_is_first_and_duplicate_profiles_are_removed(self):
        with patch.object(
            worker,
            "CFG",
            {
                "chatgpt_accounts": [
                    {"id": "one", "name": "One", "profile_dir": "profile-one"},
                    {"id": "two", "name": "Two", "profile_dir": "profile-two"},
                    {"id": "duplicate", "name": "Duplicate", "profile_dir": "profile-two"},
                ],
                "active_chatgpt_account_id": "two",
            },
        ), patch.object(worker, "PROFILE_DIR", "profile-two"):
            accounts = worker.get_chatgpt_accounts()

        self.assertEqual([account["id"] for account in accounts], ["two", "one"])


class WaitingResultTests(unittest.TestCase):
    def test_waiting_quota_has_dedicated_exit_code_without_failure_count(self):
        result = {
            "mode": "main",
            "selected_count": 1,
            "failure_count": 0,
            "waiting_quota": True,
            "waiting_reason": "Không còn tài khoản dự phòng",
            "waiting_image": "04_104.jpg",
        }
        job = {
            "total": 2,
            "done": 1,
            "failed": 0,
            "pending": 1,
            "pending_files": [Path("04_104.jpg")],
            "state": "pending",
        }
        with patch.object(worker, "get_job_state", return_value=job), patch.object(worker, "print"):
            code = worker.finish_batch_result(result, [Path("03_103.jpg"), Path("04_104.jpg")])

        self.assertEqual(code, 4)
        self.assertEqual(result["job"]["state"], "waiting_quota")
        self.assertEqual(result["job"]["waiting_image"], "04_104.jpg")
        self.assertEqual(result["failure_count"], 0)


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_is_json_and_contains_unfinished_image(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "04_104.jpg"
            source.write_bytes(b"source")
            output = Path(directory) / "output"
            with patch.object(worker, "DOWNLOAD_FOLDER", str(output)):
                worker.write_job_checkpoint(
                    job_id="job-1",
                    mode="main",
                    images=[source],
                    batch=[source],
                    position=0,
                    current_image=source.name,
                    active_account={"id": "one", "name": "One", "profile_dir": "profile-one"},
                    stage="processing",
                    state="running",
                    account_states={"one": {"state": "active"}},
                )
                payload = json.loads((output / "job_checkpoint.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["current_image"], "04_104.jpg")
        self.assertEqual(payload["state"], "running")
        self.assertEqual(payload["account_states"]["one"]["state"], "active")


class FallbackCoordinatorTests(unittest.TestCase):
    def test_quota_retries_same_image_on_next_account_and_counts_once(self):
        class Context:
            def __init__(self, page):
                self.pages = [page]
                self.closed = False

            def close(self):
                self.closed = True

        class PlaywrightScope:
            def __init__(self, playwright):
                self.playwright = playwright

            def __enter__(self):
                return self.playwright

            def __exit__(self, *_args):
                return False

        images = [Path("01_101.jpg"), Path("02_102.jpg")]
        first_page = object()
        second_page = object()
        first_context = Context(first_page)
        second_context = Context(second_page)
        process_calls = []
        events = []

        def fake_process(page, _indices, image):
            process_calls.append((page, image.name))
            if len(process_calls) == 1:
                raise worker.QuotaExhaustedError("Bạn hiện đã hết lượt tạo ảnh.")

        fake_playwright = object()
        with patch.object(worker, "RUN_MODE", "main"), \
             patch.object(worker, "SERVICE", "chatgpt"), \
             patch.object(worker, "BATCH_SIZE", 2), \
             patch.object(worker, "START_FROM", ""), \
             patch.object(worker, "ensure_dirs"), \
             patch.object(worker, "init_progress"), \
             patch.object(worker, "get_images", return_value=images), \
             patch.object(worker, "get_next_batch", return_value=images), \
             patch.object(worker, "get_job_state", return_value={"pending": 2, "pending_files": images, "state": "pending", "total": 2, "done": 0, "failed": 0}), \
             patch.object(worker, "get_chatgpt_accounts", return_value=[
                 {"id": "one", "name": "One", "profile_dir": "profile-one"},
                 {"id": "two", "name": "Two", "profile_dir": "profile-two"},
             ]), \
             patch.object(worker, "CFG", {"auto_account_fallback_enabled": True}), \
             patch.object(worker, "launch_persistent_context", return_value=first_context), \
             patch.object(worker, "open_existing_chatgpt_account", return_value=(second_context, second_page)), \
             patch.object(worker, "minimize_own_browser"), \
             patch.object(worker, "login_if_needed"), \
             patch.object(worker, "process_one", side_effect=fake_process), \
             patch.object(worker, "write_job_checkpoint"), \
             patch.object(worker, "finish_batch_result", return_value=0), \
             patch.object(worker, "emit_account_event", side_effect=lambda event, **data: events.append((event, data))), \
             patch.object(worker, "sync_playwright", return_value=PlaywrightScope(fake_playwright)), \
             patch.object(worker, "print"):
            self.assertEqual(worker.main(), 0)

        self.assertEqual(
            [(page, name) for page, name in process_calls],
            [(first_page, "01_101.jpg"), (second_page, "01_101.jpg"), (second_page, "02_102.jpg")],
        )
        self.assertEqual([event[0] for event in events], ["account_quota_exhausted", "account_switched"])
        self.assertTrue(first_context.closed)


if __name__ == "__main__":
    unittest.main()
