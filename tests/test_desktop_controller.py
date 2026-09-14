import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from desktop_controller import (
    ACCOUNT_EVENT_PREFIX,
    BATCH_RESULT_PREFIX,
    DesktopController,
    ProcessLaunch,
    Scheduler,
)


class FakeScheduler(Scheduler):
    def __init__(self):
        self.calls = []
        self.cancelled = []

    def call_later(self, delay_ms, callback):
        handle = {"delay_ms": delay_ms, "callback": callback}
        self.calls.append(handle)
        return handle

    def cancel(self, handle):
        self.cancelled.append(handle)


class FakeStdin:
    def __init__(self, error=None):
        self.error = error
        self.writes = []
        self.flush_count = 0

    def write(self, value):
        if self.error:
            raise self.error
        self.writes.append(value)

    def flush(self):
        self.flush_count += 1


class FakeProcess:
    def __init__(self, pid=42):
        self.pid = pid
        self.return_code = None
        self.stdin = FakeStdin()
        self.stdout = []
        self.terminated = False

    def poll(self):
        return self.return_code

    def wait(self):
        return 0 if self.return_code is None else self.return_code

    def terminate(self):
        self.terminated = True


class FakeThread:
    def __init__(self, **kwargs):
        self.target = kwargs["target"]
        self.args = kwargs["args"]
        self.daemon = kwargs["daemon"]
        self.started = False

    def start(self):
        self.started = True


class ProcessFactory:
    def __init__(self):
        self.processes = []
        self.calls = []

    def __call__(self, command, **kwargs):
        process = FakeProcess(pid=100 + len(self.processes))
        self.processes.append(process)
        self.calls.append((command, kwargs))
        return process


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def event_types(controller):
    return [event.type for event in controller.drain_events()]


def full_success_result(**overrides):
    result = {
        "requested_batch_size": 10,
        "selected_count": 10,
        "completed_count": 10,
        "success_count": 10,
        "failure_count": 0,
        "next_pending_count": 1,
        "exit_code": 0,
    }
    result.update(overrides)
    return result


class DesktopControllerTests(unittest.TestCase):
    def make_controller(self):
        self.scheduler = FakeScheduler()
        self.factory = ProcessFactory()
        self.terminated = []
        self.clock = Clock()
        return DesktopController(
            self.scheduler,
            popen_factory=self.factory,
            thread_factory=FakeThread,
            monotonic=self.clock,
            process_tree_terminator=self.terminated.append,
        )

    @staticmethod
    def launch(mode="main"):
        return ProcessLaunch(
            ["python", "worker.py"],
            "C:/app",
            {"RUN_MODE": mode, "PYTHONUTF8": "1"},
            0,
        )

    def test_start_main_retry_and_force_use_the_requested_launch(self):
        for mode in ("main", "retry", "force"):
            with self.subTest(mode=mode):
                controller = self.make_controller()
                self.assertTrue(controller.start(mode, self.launch(mode)))
                self.assertTrue(controller.state.running)
                self.assertEqual(controller.state.current_run_mode, mode)
                self.assertEqual(self.factory.calls[0][1]["env"]["RUN_MODE"], mode)
                self.assertIn("process_started", event_types(controller))

    def test_second_start_is_rejected_while_process_is_running(self):
        controller = self.make_controller()
        self.assertTrue(controller.start("main", self.launch()))
        self.assertFalse(controller.start("retry", self.launch("retry")))
        self.assertEqual(len(self.factory.calls), 1)

    def test_worker_output_parses_log_progress_result_account_and_manual_marker(self):
        controller = self.make_controller()
        controller.handle_worker_output("ordinary line\n")
        controller.handle_worker_output("📌 Batch lần này: 2 ảnh\n")
        controller.handle_worker_output("✓ DONE one.png\n")
        controller.handle_worker_output("MANUAL_ACTION_REQUIRED\n")
        result = full_success_result(requested_batch_size=2, selected_count=2)
        controller.handle_worker_output(BATCH_RESULT_PREFIX + json.dumps(result))
        account = {"event": "account_switched", "account_id": "two"}
        controller.handle_worker_output(ACCOUNT_EVENT_PREFIX + json.dumps(account))

        events = controller.drain_events()
        self.assertIn("ordinary line\n", controller.log_history)
        self.assertEqual(controller.state.progress_total, 2)
        self.assertEqual(controller.state.progress_done, 1)
        self.assertTrue(controller.state.manual_action_required)
        self.assertEqual(controller.state.current_batch_result, result)
        self.assertEqual(
            [event.data["event"] for event in events if event.type == "account_event"],
            [account],
        )

    def test_malformed_batch_result_remains_a_normal_log_line(self):
        controller = self.make_controller()
        malformed = BATCH_RESULT_PREFIX + "{not-json}\n"
        controller.handle_worker_output(malformed)
        self.assertIsNone(controller.state.current_batch_result)
        self.assertEqual(controller.log_history, [malformed])

    def test_manual_continue_writes_newline_and_clears_waiting_state(self):
        controller = self.make_controller()
        controller.start("main", self.launch())
        controller.drain_events()
        controller.handle_worker_output("MANUAL_ACTION_REQUIRED\n")

        self.assertTrue(controller.send_continue())
        self.assertEqual(controller.process.stdin.writes, ["\n"])
        self.assertEqual(controller.process.stdin.flush_count, 1)
        self.assertFalse(controller.state.manual_action_required)
        self.assertTrue(controller.state.current_run_intervened)
        self.assertIn("continue_sent", event_types(controller))

    def test_stop_running_uses_process_tree_terminator_and_stop_idle_is_safe(self):
        controller = self.make_controller()
        self.assertFalse(controller.stop())
        self.assertIn("no_process", event_types(controller))

        controller.start("main", self.launch())
        process = controller.process
        controller.drain_events()
        self.assertTrue(controller.stop())
        self.assertEqual(self.terminated, [process])
        self.assertTrue(controller.state.current_run_intervened)
        self.assertIn("stopped", event_types(controller))

    def test_exit_zero_failure_and_missing_result_cleanup_state(self):
        cases = (
            (0, full_success_result(job={"state": "complete", "done": 10, "total": 10}), "complete"),
            (2, full_success_result(job={"state": "needs_retry", "failed": 1}), "needs_retry"),
            (
                4,
                full_success_result(
                    job={"state": "waiting_quota", "waiting_reason": "quota", "waiting_image": "one.png"}
                ),
                "waiting_quota",
            ),
            (1, None, "done"),
        )
        for exit_code, result, expected in cases:
            with self.subTest(exit_code=exit_code, expected=expected):
                controller = self.make_controller()
                controller.start("main", self.launch())
                controller.drain_events()
                controller.state.manual_action_required = True
                controller.state.current_batch_result = result
                controller.handle_process_done(exit_code)
                events = controller.drain_events()
                outcomes = [e.data["outcome"] for e in events if e.type == "process_outcome"]
                self.assertEqual(outcomes, [expected])
                self.assertIsNone(controller.process)
                self.assertFalse(controller.state.running)
                self.assertFalse(controller.state.manual_action_required)

    def test_auto_next_eligibility_matches_existing_batch_rules(self):
        controller = self.make_controller()
        controller.configure_auto_next(True, 120)
        controller.state.current_run_mode = "main"
        controller.state.current_batch_result = full_success_result()
        self.assertEqual(controller.get_auto_next_skip_reason(0), ("", {}))

        controller.state.current_batch_result = full_success_result(failure_count=1, success_count=9)
        self.assertEqual(controller.get_auto_next_skip_reason(0)[0], "auto_skip_failed")
        controller.state.current_batch_result = full_success_result(selected_count=9)
        self.assertEqual(controller.get_auto_next_skip_reason(0)[0], "auto_skip_incomplete")
        controller.state.current_batch_result = full_success_result(next_pending_count=0)
        self.assertEqual(controller.get_auto_next_skip_reason(0)[0], "auto_skip_no_more")

    def test_auto_next_blocks_intervention_and_unverified_worker_failure(self):
        controller = self.make_controller()
        controller.configure_auto_next(True, 120)
        controller.state.current_run_mode = "main"
        controller.state.current_batch_result = full_success_result()
        controller.state.current_run_intervened = True
        self.assertEqual(controller.get_auto_next_skip_reason(0)[0], "auto_skip_intervened")
        controller.state.current_run_intervened = False
        controller.state.current_batch_result["exit_code"] = 2
        self.assertEqual(controller.get_auto_next_skip_reason(1)[0], "auto_skip_process_error")

    def test_auto_next_schedule_cancel_token_and_configuration_change(self):
        controller = self.make_controller()
        controller.configure_auto_next(True, 120)
        controller.state.current_batch_result = full_success_result()
        self.assertTrue(controller.schedule_auto_next())
        scheduled_token = controller.state.auto_next_token
        scheduled_callback = self.scheduler.calls[-1]["callback"]
        self.assertTrue(controller.state.auto_next_active)

        controller.mark_run_configuration_changed()
        self.assertFalse(controller.state.auto_next_active)
        self.assertGreater(controller.state.auto_next_token, scheduled_token)
        scheduled_callback()
        self.assertFalse(controller.state.auto_next_active)

    def test_auto_next_run_now_requests_main_start_from_shell(self):
        controller = self.make_controller()
        controller.configure_auto_next(True, 120)
        controller.start("main", self.launch())
        controller.drain_events()
        controller.state.current_batch_result = full_success_result()
        controller.handle_process_done(0)
        controller.drain_events()
        self.assertTrue(controller.state.auto_next_active)

        self.assertTrue(controller.run_auto_next_now())
        events = event_types(controller)
        self.assertEqual(len(self.factory.calls), 1)
        self.assertIn("auto_next_running", events)
        self.assertIn("auto_next_start_requested", events)

        # The shell supplies a freshly built launch, preserving account and
        # form changes that are intentionally allowed between worker runs.
        self.assertTrue(controller.start("main", self.launch(), auto_started=True))
        self.assertEqual(len(self.factory.calls), 2)

    def test_auto_next_countdown_restarts_only_for_current_token(self):
        controller = self.make_controller()
        controller.configure_auto_next(True, 1)
        controller.start("main", self.launch())
        controller.drain_events()
        controller.state.current_batch_result = full_success_result()
        controller.handle_process_done(0)
        controller.drain_events()
        token = controller.state.auto_next_token

        controller.update_auto_next_countdown(token - 1)
        self.assertEqual(len(self.factory.calls), 1)
        self.clock.now += 1
        controller.update_auto_next_countdown(token)
        events = event_types(controller)
        self.assertEqual(len(self.factory.calls), 1)
        self.assertIn("auto_next_start_requested", events)

    def test_delay_validation_rejects_non_positive_and_non_finite_values(self):
        self.assertEqual(DesktopController.parse_auto_next_delay("2"), 120)
        for value in ("0", "-1", "nan", "inf", "not a number"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                DesktopController.parse_auto_next_delay(value)

    def test_controller_source_has_no_gui_or_webview_dependency(self):
        source = (PROJECT_ROOT / "desktop_controller.py").read_text(encoding="utf-8")
        for forbidden in (
            "tkinter",
            "customtkinter",
            "CTkButton",
            "StringVar",
            "BooleanVar",
            "root.after",
            "webview",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
