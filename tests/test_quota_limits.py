"""Recovery estimates are UTC-based, localized to Vietnam, and persisted."""
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.quota_limits import QuotaLimits, reset_delay_seconds


class QuotaLimitTests(unittest.TestCase):
    def test_wait_duration_formats_and_unknown_notice(self):
        for notice, expected in [
            ("You've hit the Plus plan limit. You can create more images when the limit resets in 10 hours.", 36000),
            ("The limit resets in 1 hour and 30 minutes.", 5400),
            ("Try again in 45 minutes.", 2700),
            ("The limit resets in 1.5 hours.", 5400),
            ("Bạn có thể tạo thêm ảnh sau 5 giờ.", 18000),
            ("Giới hạn được đặt lại sau 2 giờ 15 phút.", 8100),
            ("The limit resets in 1 day, 2 hours.", 93600),
            ("You've hit the limit.", None),
            ("You created 10 images in 5 hours. Limit reached.", None),
        ]:
            with self.subTest(notice=notice):
                self.assertEqual(reset_delay_seconds(notice), expected)

    def test_vietnam_time_crosses_midnight_and_survives_reopen(self):
        observed = datetime(2026, 10, 4, 11, 40, tzinfo=timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quota_limits.json"
            store = QuotaLimits(path, clock=lambda: observed + 600)
            store.record({"account_id": "personal", "account_name": "Vung-Personal",
                          "detected_at": observed, "evidence": "The limit resets in 10 hours."})
            rows = store.snapshot()
            self.assertEqual(rows[0]["detected_vn"], "04/10/2026 18:40")
            self.assertEqual(rows[0]["reset_vn_full"], "05/10/2026 04:40")
            self.assertEqual(rows[0]["reset_at"], observed + 36000)
            restored = QuotaLimits(path, clock=lambda: observed + 37000).snapshot()
            self.assertEqual(restored[0]["reset_vn"], "05/10 04:40")
            self.assertTrue(restored[0]["estimate_due"])

    def test_multiple_accounts_update_one_record_and_preserve_unknown_time(self):
        with tempfile.TemporaryDirectory() as directory:
            store = QuotaLimits(Path(directory) / "quota_limits.json", clock=lambda: 100000)
            for identity, notice in [("one", "The limit resets in 2 hours."),
                                     ("two", "You've hit the Business plan limit.")]:
                store.record({"account_id": identity, "account_name": identity, "evidence": notice})
            store.record({"account_id": "one", "account_name": "Renamed", "evidence": "The limit resets in 3 hours."})
            rows = {item["account_id"]: item for item in store.snapshot()}
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows["one"]["reset_at"], 110800)
            self.assertIsNone(rows["two"]["reset_at"])
            self.assertFalse(rows["two"]["estimate_due"])

    def test_both_workers_keep_first_detection_time_while_notice_streams(self):
        import run_chatgpt_batch as stable
        import run_chatgpt_batch_books34 as isolated
        for worker in (stable, isolated):
            with self.subTest(worker=worker.__name__):
                now = [100]
                def sleep(seconds):
                    now[0] += seconds
                notice = "The limit resets in 10 hours."
                with patch.object(worker, "time", SimpleNamespace(time=lambda: now[0])), \
                     patch.object(worker, "sleep", side_effect=sleep), patch.object(worker, "print"), \
                     patch.object(worker, "is_generating", return_value=False), \
                     patch.object(worker, "get_generation_quota_evidence", return_value=notice), \
                     self.assertRaises(worker.QuotaExhaustedError) as caught:
                    worker.raise_image_quota_error(object(), notice, {})
                self.assertGreater(now[0], 100)
                self.assertEqual(caught.exception.detected_at, 100)

    def test_book_files_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one, two = QuotaLimits(root / "quota_limits.json"), QuotaLimits(root / "book-2/quota_limits.json")
            one.record({"account_id": "default", "account_name": "One", "evidence": "The limit resets in 10 hours."})
            self.assertEqual(two.snapshot(), [])


if __name__ == "__main__":
    unittest.main()
