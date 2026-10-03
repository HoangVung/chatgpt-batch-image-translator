"""Auth-state and single-Continue regressions; no real accounts or profiles."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORKERS = []
for filename in ("run_chatgpt_batch.py", "run_chatgpt_batch_books34.py"):
    spec = importlib.util.spec_from_file_location("login_test_" + Path(filename).stem, ROOT / filename)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    WORKERS.append(worker)


class Clock:
    def __init__(self):
        self.now = 0

    def advance(self, seconds):
        self.now += seconds


class Locator:
    def __init__(self, page, selector, index=None):
        self.page, self.selector, self.index = page, selector, index

    @property
    def first(self):
        return self.nth(0)

    def nth(self, index):
        return Locator(self.page, self.selector, index)

    def count(self):
        state = self.page.state()
        if self.selector == "body":
            return 1
        if self.selector.startswith("#prompt-textarea"):
            return int(state in {"guest", "hydrating", "ready", "hidden"})
        if self.selector == self.page.signin_selector:
            return 2 if state == "guest-hidden-first" else int(state in {"guest", "hydrating"})
        return 0

    def is_visible(self):
        if self.page.state() == "guest-hidden-first":
            return self.index == 1
        return self.count() > 0 and self.page.state() != "hidden"

    def inner_text(self, timeout=None):
        return "Verify you are human" if self.page.state() == "challenge" else "Ask anything"


class Page:
    def __init__(self, state, service="chatgpt"):
        self._state = state
        self.url = "https://chatgpt.com/"
        self.signin_selector = ('button:has-text("Đăng nhập")' if service == "gemini"
                                else 'button:has-text("Log in")')

    def state(self):
        return self._state() if callable(self._state) else self._state

    def goto(self, url, **kwargs):
        self.url = url

    def locator(self, selector):
        return Locator(self, selector)

    def evaluate(self, expression):
        if expression.endswith(".editor_index"):
            return 0 if self.state() in {"guest", "hydrating", "ready"} else -1
        raise AssertionError("Unexpected composer probe")


class LoginFlowTests(unittest.TestCase):
    def exercise(self, worker, page, operation, continuation=None):
        clock = getattr(page, "clock", Clock())
        with patch.object(worker.time, "monotonic", side_effect=lambda: clock.now), \
             patch.object(worker, "sleep", side_effect=clock.advance), \
             patch.object(worker, "check_stop_requested"), \
             patch.object(worker, "print") as output, \
             patch.object(worker, "wait_for_continue", side_effect=continuation) as wait:
            result = operation()
        return result, wait, output, clock

    def test_saved_session_hydration_does_not_request_login_again(self):
        for worker in WORKERS:
            with self.subTest(worker=worker.__name__):
                clock = Clock()
                page = Page(lambda: "hydrating" if clock.now < 2 else "ready")
                page.clock = clock
                _, wait, output, _ = self.exercise(worker, page, lambda: worker.login_if_needed(page))
                wait.assert_not_called()
                self.assertFalse(any("MANUAL_ACTION_REQUIRED" in str(call) for call in output.call_args_list))

    def test_first_login_needs_one_continue_and_rechecks_hydration(self):
        for worker in WORKERS:
            for service in ("chatgpt", "gemini"):
                with self.subTest(worker=worker.__name__, service=service):
                    clock = Clock()
                    continued_at = []
                    page = Page(lambda: "guest" if not continued_at else
                                "hydrating" if clock.now - continued_at[0] < 2 else "ready", service)
                    page.clock = clock
                    _, wait, output, _ = self.exercise(
                        worker, page, lambda: worker.login_if_needed(page, service=service),
                        continuation=lambda _prompt: continued_at.append(clock.now),
                    )
                    wait.assert_called_once()
                    self.assertEqual(sum("MANUAL_ACTION_REQUIRED" in str(call) for call in output.call_args_list), 1)

    def test_challenge_and_login_share_one_continue(self):
        for worker in WORKERS:
            with self.subTest(worker=worker.__name__):
                page = Page("challenge")
                _, wait, output, _ = self.exercise(
                    worker, page, lambda: worker.login_if_needed(page),
                    continuation=lambda _prompt: setattr(page, "_state", "ready"),
                )
                wait.assert_called_once()
                self.assertEqual(sum("MANUAL_ACTION_REQUIRED" in str(call) for call in output.call_args_list), 1)

    def test_guest_composer_is_not_accepted_after_continue(self):
        for worker in WORKERS:
            with self.subTest(worker=worker.__name__):
                page = Page("guest")
                with patch.object(worker, "wait_for_continue") as wait:
                    clock = Clock()
                    with patch.object(worker.time, "monotonic", side_effect=lambda: clock.now), \
                         patch.object(worker, "sleep", side_effect=clock.advance), \
                         patch.object(worker, "check_stop_requested"), patch.object(worker, "print"):
                        with self.assertRaisesRegex(Exception, "chưa đăng nhập"):
                            worker.login_if_needed(page)
                    wait.assert_called_once()

    def test_fallback_guest_composer_is_not_a_saved_session(self):
        for worker in WORKERS:
            with self.subTest(worker=worker.__name__):
                page = Page("guest")
                ready, wait, _, _ = self.exercise(worker, page, lambda: worker.wait_existing_chatgpt_session(page))
                self.assertFalse(ready)
                wait.assert_not_called()

    def test_fallback_challenge_never_blocks_for_manual_input(self):
        for worker in WORKERS:
            with self.subTest(worker=worker.__name__):
                page = Page("challenge")
                ready, wait, _, _ = self.exercise(worker, page, lambda: worker.wait_existing_chatgpt_session(page))
                self.assertFalse(ready)
                wait.assert_not_called()

    def test_hidden_composer_is_not_a_ready_session(self):
        for worker in WORKERS:
            with self.subTest(worker=worker.__name__):
                page = Page("hidden")
                ready, wait, _, clock = self.exercise(worker, page, lambda: worker.wait_signed_in_session(page, timeout=7))
                self.assertFalse(ready)
                self.assertEqual(clock.now, 7)
                wait.assert_not_called()

    def test_hidden_first_signin_does_not_hide_a_visible_duplicate(self):
        for worker in WORKERS:
            with self.subTest(worker=worker.__name__):
                self.assertTrue(worker.has_signin_prompt(Page("guest-hidden-first")))

    def test_login_closes_context_on_completion_or_cooperative_stop(self):
        for worker in WORKERS:
            for stop in (False, True):
                with self.subTest(worker=worker.__name__, stop=stop):
                    playwright = MagicMock()
                    context = MagicMock()
                    with patch.object(worker, "sync_playwright", return_value=playwright), \
                         patch.object(worker, "ensure_profile_dir"), \
                         patch.object(worker, "check_stop_requested"), \
                         patch.object(worker, "print"), \
                         patch.object(worker, "launch_persistent_context", return_value=context) as launch, \
                         patch.object(worker, "login_if_needed", side_effect=worker.WorkerStopRequested() if stop else None):
                        if stop:
                            with self.assertRaises(worker.WorkerStopRequested):
                                worker.login_only()
                        else:
                            self.assertEqual(worker.login_only(), 0)
                    launch.assert_called_once_with(playwright.__enter__.return_value, worker.PROFILE_DIR)
                    context.close.assert_called_once()

    def test_fallback_closes_context_when_stopped_before_returning_it(self):
        for worker in WORKERS:
            with self.subTest(worker=worker.__name__):
                context = MagicMock()
                with patch.object(worker.os, "makedirs"), \
                     patch.object(worker, "launch_persistent_context", return_value=context), \
                     patch.object(worker, "wait_existing_chatgpt_session", side_effect=worker.WorkerStopRequested()):
                    with self.assertRaises(worker.WorkerStopRequested):
                        worker.open_existing_chatgpt_account(object(), {"name": "Test", "profile_dir": "test-only-profile"})
                context.close.assert_called_once()

    def test_launch_uses_prepared_profile_location(self):
        for worker in WORKERS:
            with self.subTest(worker=worker.__name__):
                playwright = MagicMock()
                with patch.object(worker, "prepare_profile_dir", return_value=Path("local-profile")) as prepare, \
                     patch.object(worker, "check_stop_requested"):
                    worker.launch_persistent_context(playwright, "configured-profile")
                prepare.assert_called_once_with("configured-profile")
                self.assertEqual(playwright.chromium.launch_persistent_context.call_args.kwargs["user_data_dir"], "local-profile")


if __name__ == "__main__":
    unittest.main()
