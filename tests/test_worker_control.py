import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker_control import (STOP_FILE_ENV, WorkerStopRequested,
                            check_stop_requested, cooperative_sleep, wait_for_continue)


class WorkerControlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.stop_file = Path(self.directory.name) / "stop"
        self.environment = patch.dict(os.environ, {STOP_FILE_ENV: str(self.stop_file)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_stop_bypasses_image_exception_handler_and_runs_finally(self):
        self.stop_file.touch()
        finalizers = []
        errors = []
        with self.assertRaises(WorkerStopRequested):
            try:
                try:
                    check_stop_requested()
                except Exception:
                    errors.append("image-failed")
            finally:
                finalizers.append("browser-closed")
        self.assertEqual(errors, [])
        self.assertEqual(finalizers, ["browser-closed"])

    def test_sleep_observes_stop_requested_during_cooldown(self):
        timer = threading.Timer(0.03, self.stop_file.touch)
        timer.start()
        try:
            with self.assertRaises(WorkerStopRequested):
                cooperative_sleep(30)
        finally:
            timer.join()

    def test_manual_input_can_stop_without_enter(self):
        release = threading.Event()
        entered = threading.Event()

        def blocked_input(prompt):
            entered.set()
            release.wait(3)
            return ""

        def stop_after_input():
            entered.wait(3)
            self.stop_file.touch()

        stopper = threading.Thread(target=stop_after_input)
        stopper.start()
        try:
            with patch("builtins.input", side_effect=blocked_input):
                with self.assertRaises(WorkerStopRequested):
                    wait_for_continue("Continue")
        finally:
            release.set()
            stopper.join()

    def test_continue_reads_exactly_one_enter(self):
        with patch("builtins.input", return_value="") as read:
            self.assertEqual(wait_for_continue("Continue"), "")
        read.assert_called_once_with("Continue")

    def test_eof_is_propagated_instead_of_treated_as_continue(self):
        with patch("builtins.input", side_effect=EOFError):
            with self.assertRaises(EOFError):
                wait_for_continue("Continue")

    def test_cli_without_control_marker_keeps_normal_input_and_sleep(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("builtins.input", return_value="done") as read:
                self.assertEqual(wait_for_continue("Continue"), "done")
            read.assert_called_once_with("Continue")
            with patch("worker_control.time.sleep") as sleeper:
                cooperative_sleep(7)
            sleeper.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
