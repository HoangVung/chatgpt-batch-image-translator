import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from desktop.web_scheduler import WebScheduler


class FakeTimer:
    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class WebSchedulerTests(unittest.TestCase):
    def test_call_later_uses_milliseconds_and_cancel(self):
        timers = []
        scheduler = WebScheduler(lambda delay, callback: timers.append(FakeTimer(delay, callback)) or timers[-1])
        handle = scheduler.call_later(1500, lambda: None)
        self.assertEqual(handle.delay, 1.5)
        self.assertTrue(handle.started)
        self.assertTrue(handle.daemon)
        scheduler.cancel(handle)
        self.assertTrue(handle.cancelled)

    def test_shutdown_cancels_pending_and_blocks_callbacks(self):
        timers, calls = [], []
        scheduler = WebScheduler(lambda delay, callback: timers.append(FakeTimer(delay, callback)) or timers[-1])
        scheduler.call_later(1, lambda: calls.append("called"))
        scheduler.shutdown()
        self.assertTrue(timers[0].cancelled)
        timers[0].callback()
        self.assertEqual(calls, [])
        with self.assertRaises(RuntimeError):
            scheduler.call_later(1, lambda: None)


if __name__ == "__main__":
    unittest.main()
