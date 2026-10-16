"""Offline worker recovery tests; never connect to a provider or send a prompt."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_chatgpt_batch_books34 as worker


class SendRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0.0
        self.page = Mock()
        self.page.url = "https://chatgpt.com/c/6acc804e-7d4c-83ec-852d-be499a4d1889"
        self.text = worker.PROMPT_DICH
        self.reloaded = False
        self.state = {
            "reason": "ready", "editor_count": 1, "editable": True,
            "composer_found": True, "attachment_count": 0, "uploading": False,
            "generating": False, "upload_error": False,
        }
        self.baseline = {
            "url": self.page.url,
            "users": [worker.PROMPT_CHEP_LAI],
            "assistant": ["A completed transcription with its formulas."],
        }
        self.page.reload.side_effect = self.reload
        self.patch(worker, "time", SimpleNamespace(
            monotonic=lambda: self.clock, time=lambda: self.clock))
        self.patch(worker, "sleep", self.advance)
        self.patch(worker, "SERVICE", "chatgpt")
        self.patch(worker, "wait_if_cloudflare", Mock())
        self.patch(worker, "print", Mock())
        self.patch(worker.composer, "diagnostic", Mock())
        self.inspect = self.patch(worker.composer, "inspect", Mock(
            side_effect=lambda page: dict(self.state)))
        self.send_ready = self.patch(worker.composer, "send_ready", Mock(
            side_effect=lambda page: self.reloaded))
        self.snapshot = self.patch(worker, "get_send_recovery_snapshot", Mock(
            side_effect=lambda page: copy.deepcopy(self.baseline)))
        self.focus = self.patch(worker, "safe_click_prompt", Mock(return_value=True))
        self.clear = self.patch(worker, "clear_prompt_box", Mock(
            side_effect=lambda page: self.set_text("")))
        self.fill = self.patch(worker, "fill_prompt_box", Mock(
            side_effect=lambda page, text: self.set_text(text)))
        self.read_text = self.patch(worker, "get_prompt_text", Mock(
            side_effect=lambda page: self.text))
        self.click = self.patch(worker, "click_send_button", Mock(return_value=True))
        self.verify = self.patch(worker, "verify_prompt_sent", Mock(return_value=True))
        self.patch(worker, "wait_prompt_ready", Mock(return_value=True))
        self.editor = Mock()
        self.patch(worker, "get_prompt_locator", Mock(return_value=self.editor))
        self.env = patch.dict(worker.os.environ, {"BATCH_PROVENANCE_EVENTS": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def patch(self, obj, name, value):
        patcher = patch.object(obj, name, value)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def advance(self, seconds):
        self.clock += max(0.001, seconds)

    def set_text(self, text):
        self.text = text

    def reload(self, *args, **kwargs):
        self.reloaded = True
        self.text = ""

    def assert_no_submission(self):
        self.click.assert_not_called()
        self.editor.press.assert_not_called()

    def test_ready_button_needs_no_reload_or_refill(self):
        self.send_ready.side_effect = None
        self.send_ready.return_value = True
        worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_not_called()
        self.fill.assert_not_called()
        self.assert_no_submission()

    def test_one_reload_restores_translation_draft_without_submitting(self):
        worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_called_once()
        self.fill.assert_called_once_with(self.page, worker.PROMPT_DICH)
        self.assertEqual(self.text, worker.PROMPT_DICH)
        self.assertGreaterEqual(self.snapshot.call_count, 3)
        self.assert_no_submission()

    def test_one_reload_also_recovers_image_generation_followup(self):
        self.text = worker.PROMPT_TAO_ANH
        worker.prepare_send_button(self.page, worker.PROMPT_TAO_ANH)
        self.page.reload.assert_called_once()
        self.fill.assert_called_once_with(self.page, worker.PROMPT_TAO_ANH)
        self.assert_no_submission()

    def test_missing_button_after_reload_stops_once_without_enter(self):
        self.send_ready.side_effect = None
        self.send_ready.return_value = False
        with self.assertRaises(worker.SendNotReadyError):
            worker.send_prompt(self.page, worker.PROMPT_DICH, max_send_attempts=4)
        self.page.reload.assert_called_once()
        self.assertEqual(self.fill.call_count, 2)
        self.assert_no_submission()

    def test_initial_transcription_keeps_upload_and_never_reloads(self):
        self.state["attachment_count"] = 1
        self.text = worker.PROMPT_CHEP_LAI
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_CHEP_LAI)
        self.page.reload.assert_not_called()
        self.assertEqual(self.text, worker.PROMPT_CHEP_LAI)
        self.assert_no_submission()

    def test_other_service_does_not_reload(self):
        worker.SERVICE = "gemini"
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_not_called()
        self.assert_no_submission()

    def test_only_exact_existing_chat_urls_can_reload(self):
        for url in (
            "https://chatgpt.com/", "https://chatgpt.com/c/",
            "https://chatgpt.com/c/abc?temporary-chat=true",
            "https://chatgpt.com.evil.example/c/abc",
            "https://other.example/c/abc", "http://chatgpt.com/c/abc",
        ):
            with self.subTest(url=url):
                self.page.url = url
                self.baseline["url"] = url
                with self.assertRaises(worker.SendNotReadyError):
                    worker.prepare_send_button(self.page, worker.PROMPT_DICH)
                self.page.reload.assert_not_called()
        self.assert_no_submission()

    def test_unsafe_current_composer_never_reloads(self):
        original = dict(self.state)
        for update in (
            {"attachment_count": 1}, {"uploading": True},
            {"generating": True}, {"upload_error": True},
            {"editor_count": 2}, {"reason": "composer_missing"},
        ):
            with self.subTest(update=update):
                self.state = dict(original, **update)
                with self.assertRaises(worker.SendNotReadyError):
                    worker.prepare_send_button(self.page, worker.PROMPT_DICH)
                self.page.reload.assert_not_called()
        self.assert_no_submission()

    def test_draft_mismatch_never_reloads(self):
        self.text = "An unsent manual draft"
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_not_called()
        self.fill.assert_not_called()
        self.assert_no_submission()

    def test_unreadable_composer_never_reloads(self):
        self.read_text.side_effect = RuntimeError("Composer disconnected")
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_not_called()
        self.assert_no_submission()

    def test_unreadable_transcript_never_reloads(self):
        self.snapshot.side_effect = RuntimeError("Execution context destroyed")
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_not_called()
        self.assert_no_submission()

    def test_transcript_changing_before_reload_is_rejected(self):
        changed = copy.deepcopy(self.baseline)
        changed["assistant"].append("An unexpected new reply")
        self.snapshot.side_effect = [copy.deepcopy(self.baseline), changed]
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_not_called()
        self.assert_no_submission()

    def test_reload_timeout_does_not_retry_reload_or_send(self):
        self.page.reload.side_effect = PlaywrightTimeoutError("reload timeout")
        with self.assertRaises(worker.SendNotReadyError):
            worker.send_prompt(self.page, worker.PROMPT_DICH, max_send_attempts=4)
        self.page.reload.assert_called_once()
        self.assert_no_submission()

    def test_changed_chat_after_reload_is_rejected(self):
        def snapshot(page):
            result = copy.deepcopy(self.baseline)
            if self.reloaded:
                self.page.url = "https://chatgpt.com/c/different-conversation"
                result["url"] = self.page.url
            return result
        self.snapshot.side_effect = snapshot
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_called_once()
        self.fill.assert_not_called()
        self.assert_no_submission()

    def test_changed_messages_after_reload_are_rejected(self):
        def snapshot(page):
            result = copy.deepcopy(self.baseline)
            if self.reloaded:
                result["users"].append("A concurrently submitted prompt")
            return result
        self.snapshot.side_effect = snapshot
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_called_once()
        self.fill.assert_not_called()
        self.assert_no_submission()

    def test_temporarily_unhydrated_transcript_can_recover(self):
        self.snapshot.side_effect = [copy.deepcopy(self.baseline),
                                     copy.deepcopy(self.baseline),
                                     {"url": self.page.url, "users": [], "assistant": []},
                                     copy.deepcopy(self.baseline),
                                     copy.deepcopy(self.baseline)]
        worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_called_once()
        self.fill.assert_called_once_with(self.page, worker.PROMPT_DICH)
        self.assert_no_submission()

    def test_active_generation_after_reload_is_never_submitted(self):
        def inspect(page):
            return dict(self.state, generating=self.reloaded,
                        reason="generating" if self.reloaded else "ready")
        self.inspect.side_effect = inspect
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_called_once()
        self.fill.assert_not_called()
        self.assert_no_submission()

    def test_wait_send_ready_polls_without_clicking_or_reloading(self):
        self.send_ready.side_effect = [False, False, True]
        self.assertTrue(worker.wait_send_ready(self.page, timeout=8))
        self.assertEqual(self.send_ready.call_count, 3)
        self.page.reload.assert_not_called()
        self.assert_no_submission()

    def test_empty_transcript_does_not_reload(self):
        for key in ("users", "assistant"):
            with self.subTest(key=key):
                original = self.baseline[key]
                self.baseline[key] = []
                with self.assertRaises(worker.SendNotReadyError):
                    worker.prepare_send_button(self.page, worker.PROMPT_DICH)
                self.baseline[key] = original
                self.page.reload.assert_not_called()
        self.assert_no_submission()

    def test_attachment_after_reload_prevents_refill(self):
        self.inspect.side_effect = lambda page: dict(
            self.state, attachment_count=int(self.reloaded))
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_called_once()
        self.fill.assert_not_called()
        self.assert_no_submission()

    def test_transcript_read_failure_after_reload_does_not_refill(self):
        def snapshot(page):
            if self.reloaded:
                raise RuntimeError("Conversation is not readable")
            return copy.deepcopy(self.baseline)
        self.snapshot.side_effect = snapshot
        with self.assertRaises(worker.SendNotReadyError):
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_called_once()
        self.fill.assert_not_called()
        self.assert_no_submission()

    def test_conversation_changed_after_refill_prevents_submit(self):
        def fill(page, text):
            self.set_text(text)
            if self.reloaded:
                self.baseline["assistant"].append("Concurrent response")
        self.fill.side_effect = fill
        with self.assertRaises(worker.SendNotReadyError):
            worker.send_prompt(self.page, worker.PROMPT_DICH)
        self.page.reload.assert_called_once()
        self.assert_no_submission()

    def test_uncertain_click_after_recovery_never_reloads_again(self):
        self.click.side_effect = PlaywrightTimeoutError("Timeout after click delivery")
        with self.assertRaises(worker.PromptSendUncertainError):
            worker.send_prompt(self.page, worker.PROMPT_DICH, max_send_attempts=4)
        self.page.reload.assert_called_once()
        self.click.assert_called_once_with(self.page)
        self.verify.assert_not_called()
        self.editor.press.assert_not_called()

    def assert_resend_failure_propagates(self, error):
        generating = self.patch(worker, "is_generating", Mock(return_value=False))
        new_response = self.patch(worker, "has_new_assistant_response", Mock(return_value=False))
        self.patch(worker, "get_assistant_response_signature", Mock(return_value={"count": 1}))
        resend = self.patch(worker, "send_prompt", Mock(side_effect=error))
        stable = self.patch(worker, "wait_assistant_response_stable", Mock())
        with self.assertRaises(type(error)) as caught:
            worker.wait_response_after_send(
                self.page, timeout_start=2, resend_text=worker.PROMPT_DICH,
                before_signature={"count": 1})
        self.assertIs(caught.exception, error)
        resend.assert_called_once_with(self.page, worker.PROMPT_DICH, max_send_attempts=2)
        self.assertEqual(generating.call_count, 2)
        self.assertEqual(new_response.call_count, 2)
        self.assertEqual(self.clock, 2.0)
        stable.assert_not_called()
        self.page.reload.assert_not_called()

    def test_response_wait_propagates_send_not_ready_without_second_wait(self):
        self.assert_resend_failure_propagates(worker.SendNotReadyError("No safe send button"))

    def test_response_wait_propagates_uncertain_resend_without_second_wait(self):
        self.assert_resend_failure_propagates(worker.PromptSendUncertainError("Click outcome unknown"))

    def test_response_wait_propagates_worker_stop(self):
        self.assert_resend_failure_propagates(worker.WorkerStopRequested())

    def test_stop_during_recovery_is_not_wrapped_as_send_error(self):
        stop = worker.WorkerStopRequested()
        self.page.reload.side_effect = stop
        with self.assertRaises(worker.WorkerStopRequested) as caught:
            worker.prepare_send_button(self.page, worker.PROMPT_DICH)
        self.assertIs(caught.exception, stop)
        self.page.reload.assert_called_once()
        self.assert_no_submission()

    def test_recovered_draft_is_clicked_once_and_verified(self):
        self.assertTrue(worker.send_prompt(self.page, worker.PROMPT_DICH))
        self.page.reload.assert_called_once()
        self.click.assert_called_once_with(self.page)
        self.verify.assert_called_once()
        self.editor.press.assert_not_called()

    def test_click_timeout_is_terminal_without_second_click_or_reload(self):
        self.send_ready.side_effect = None
        self.send_ready.return_value = True
        self.click.side_effect = PlaywrightTimeoutError("Timeout after click delivery")
        with self.assertRaises(worker.PromptSendUncertainError):
            worker.send_prompt(self.page, worker.PROMPT_DICH, max_send_attempts=4)
        self.click.assert_called_once_with(self.page)
        self.page.reload.assert_not_called()
        self.verify.assert_not_called()
        self.editor.press.assert_not_called()

    def test_verify_false_is_terminal_without_second_click_or_reload(self):
        self.send_ready.side_effect = None
        self.send_ready.return_value = True
        self.verify.return_value = False
        with self.assertRaises(worker.PromptSendUncertainError):
            worker.send_prompt(self.page, worker.PROMPT_DICH, max_send_attempts=4)
        self.click.assert_called_once_with(self.page)
        self.page.reload.assert_not_called()
        self.editor.press.assert_not_called()

    def test_missing_composer_after_click_is_terminal(self):
        self.send_ready.side_effect = None
        self.send_ready.return_value = True
        self.verify.side_effect = RuntimeError("Composer disappeared during verification")
        with self.assertRaises(worker.PromptSendUncertainError):
            worker.send_prompt(self.page, worker.PROMPT_DICH, max_send_attempts=4)
        self.click.assert_called_once_with(self.page)
        self.page.reload.assert_not_called()
        self.editor.press.assert_not_called()

    def test_ready_button_disappearing_before_click_never_falls_back_to_enter(self):
        self.send_ready.side_effect = None
        self.send_ready.return_value = True
        self.click.return_value = False
        with self.assertRaises(worker.SendNotReadyError):
            worker.send_prompt(self.page, worker.PROMPT_DICH, max_send_attempts=4)
        self.click.assert_called_once_with(self.page)
        self.verify.assert_not_called()
        self.page.reload.assert_not_called()
        self.editor.press.assert_not_called()


if __name__ == "__main__":
    unittest.main()
