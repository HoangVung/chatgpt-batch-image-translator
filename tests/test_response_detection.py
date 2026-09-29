"""Real DOM regressions for response completion; no account or network required."""
import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from html import escape
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def current_chatgpt_unit(role, text, turn=0):
    """Sanitized structure captured from the affected ChatGPT conversation."""
    message_index = 0 if role == "user" else 1
    key = f"fallback-turn-{turn}:{message_index}:{role}"
    return f"""
        <div data-content-search-unit-key="{key}" data-chatgpt-search-unit-key="{key}">
            <div class="group flex min-w-0 flex-col" data-chatgpt-selection-message-id="fixture-{turn}-{role}">
                <div data-markdown-text-style="{role}-message" class="MarkdownRoot-rZKhxa" dir="auto">
                    <p class="Paragraph-kKnbIo" data-markdown-han-text="true" dir="auto">{escape(text)}</p>
                </div>
            </div>
        </div>
    """


class ResponseDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright

            manager = sync_playwright()
            if manager is None or not hasattr(manager, "start"):
                raise ImportError("Playwright is not available or mocked")
        except (ImportError, AttributeError):
            raise unittest.SkipTest("Playwright is required for browser response tests")

        spec = importlib.util.spec_from_file_location(
            "response_worker", PROJECT_ROOT / "run_chatgpt_batch.py"
        )
        cls.worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.worker)
        cls.playwright = manager.start()
        try:
            options = {"headless": True}
            if os.environ.get("BATCH_TEST_BROWSER"):
                options["executable_path"] = os.environ["BATCH_TEST_BROWSER"]
            cls.browser = cls.playwright.chromium.launch(**options)
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def assert_response(self, text):
        signature = self.worker.get_assistant_response_signature(self.page)
        self.assertEqual(signature["count"], 1, signature)
        self.assertEqual(signature["last_len"], len(text), signature)
        self.assertEqual(signature["last_tail"], text, signature)
        return signature

    def test_current_chatgpt_user_unit_and_heading_are_not_a_response(self):
        self.page.set_content(f"""
            <main><div data-content-search-turn-key="fallback-turn-0">
                <h4 class="sr-only">You said:</h4>
                {current_chatgpt_unit("user", "chép lại nguyên văn")}
                <h4 class="sr-only" data-conversation-role="assistant">ChatGPT said:</h4>
            </div></main>
        """)
        signature = self.worker.get_assistant_response_signature(self.page)
        self.assertEqual(signature["count"], 0, signature)
        self.assertEqual(signature["last_len"], 0, signature)

    def test_current_chatgpt_transcription_and_follow_up_translation(self):
        self.page.set_content(f"""
            <main><div id="turns"><div id="first-turn" data-content-search-turn-key="fallback-turn-0">
                {current_chatgpt_unit("user", "chép lại nguyên văn")}
            </div></div></main>
        """)
        before = self.worker.get_assistant_response_signature(self.page)
        self.page.locator("#first-turn").evaluate(
            "(node, markup) => node.insertAdjacentHTML('beforeend', markup)",
            current_chatgpt_unit("assistant", "函数迭代与函数方程"),
        )
        self.assertTrue(self.worker.has_new_assistant_response(self.page, before))
        transcribed = self.assert_response("函数迭代与函数方程")
        self.page.locator("#turns").evaluate(
            "(node, markup) => node.insertAdjacentHTML('beforeend', markup)",
            '<div data-content-search-turn-key="fallback-turn-1">'
            + current_chatgpt_unit("user", "Dịch sang tiếng Việt", turn=1)
            + current_chatgpt_unit("assistant", "Phép lặp hàm và phương trình hàm", turn=1)
            + '</div>',
        )
        self.assertTrue(self.worker.has_new_assistant_response(self.page, transcribed))
        translated = self.worker.get_assistant_response_signature(self.page)
        self.assertEqual(translated["count"], 2, translated)
        self.assertEqual(translated["last_tail"], "Phép lặp hàm và phương trình hàm", translated)
        self.assertFalse(self.worker.has_new_assistant_response(self.page, translated))

    def test_current_chatgpt_quota_guard_uses_new_assistant_unit_only(self):
        quota = "You've hit the image generation limit."
        self.page.set_content(
            '<main><div id="turns"><div data-content-search-turn-key="fallback-turn-0">'
            + current_chatgpt_unit("user", "Tạo ảnh")
            + current_chatgpt_unit("assistant", quota)
            + '</div></div></main>'
        )
        before = self.worker.get_assistant_response_signature(self.page)
        self.page.locator("#turns").evaluate(
            "(node, markup) => node.insertAdjacentHTML('beforeend', markup)",
            '<div data-content-search-turn-key="fallback-turn-1">'
            + current_chatgpt_unit("user", quota, turn=1)
            + current_chatgpt_unit("assistant", "升级版", turn=1)
            + '</div>',
        )
        self.assertTrue(self.worker.has_new_assistant_response(self.page, before))
        self.assertIsNone(self.worker.get_generation_quota_evidence(self.page, before))
        before = self.worker.get_assistant_response_signature(self.page)
        self.page.locator("#turns").evaluate(
            "(node, markup) => node.insertAdjacentHTML('beforeend', markup)",
            '<div data-content-search-turn-key="fallback-turn-2">'
            + current_chatgpt_unit("user", "Tạo ảnh", turn=2)
            + current_chatgpt_unit("assistant", quota, turn=2)
            + '</div>',
        )
        self.assertEqual(self.worker.get_generation_quota_evidence(self.page, before), quota)

    def test_evaluation_failure_is_retained_in_signature(self):
        class BrokenPage:
            def evaluate(self, script, arg=None):
                raise RuntimeError("response read failed")

        signature = self.worker.get_assistant_response_signature(BrokenPage())
        self.assertEqual(signature["count"], 0, signature)
        self.assertEqual(signature["last_len"], 0, signature)
        self.assertEqual(signature["last_tail"], "", signature)
        self.assertIn("response read failed", signature.get("error", ""), signature)

    def test_wait_logs_signature_counts_and_evaluation_failure(self):
        class BrokenPage:
            url = "https://example.test/chat"

            def evaluate(self, script, arg=None):
                raise RuntimeError("response read failed")

        class Clock:
            now = 100

            def time(clock):
                return clock.now

            def sleep(clock, seconds):
                clock.now += seconds

        clock = Clock()
        before = {"count": 2, "last_len": 21, "last_tail": "private baseline text"}
        output = io.StringIO()
        with patch.object(self.worker, "time", clock), patch.object(
            self.worker, "sleep", clock.sleep
        ), patch.object(self.worker, "wait_if_cloudflare"), patch.object(
            self.worker, "is_generating", return_value=False
        ), redirect_stdout(output):
            self.assertFalse(
                self.worker.wait_assistant_response_stable(
                    BrokenPage(), before, stable_seconds=3, timeout=3
                )
            )
        logs = output.getvalue()
        self.assertIn("before=2", logs)
        self.assertIn("current=0", logs)
        self.assertIn("response read failed", logs)
        self.assertNotIn("private baseline text", logs)

    def test_icon_only_assistant_controls_do_not_hide_completed_response(self):
        self.page.set_content("""
            <main><article data-testid="conversation-turn-2" data-turn="assistant">
                <div data-message-author-role="assistant">
                    <div class="markdown">函数迭代与函数方程</div>
                    <button data-testid="assistant-actions-menu" aria-label="More">
                        <svg width="16" height="16"><circle cx="8" cy="8" r="2"/></svg>
                    </button>
                </div>
            </article></main>
        """)
        self.assert_response("函数迭代与函数方程")

    def test_empty_matching_descendant_does_not_replace_message_text(self):
        self.page.set_content("""
            <main><div data-message-author-role="assistant">
                <div class="markdown">上海科技教育出版社</div>
                <div data-testid="assistant-loading-placeholder"></div>
            </div></main>
        """)
        self.assert_response("上海科技教育出版社")

    def test_empty_turn_does_not_disable_markdown_fallback(self):
        self.page.set_content("""
            <main>
                <article data-testid="conversation-turn-2"></article>
                <section><div class="markdown">升级版</div></section>
            </main>
        """)
        self.assert_response("升级版")

    def test_controls_only_wrapper_is_not_a_response(self):
        self.page.set_content("""
            <main><article data-turn="assistant" data-testid="conversation-turn-2">
                <div data-message-author-role="assistant">
                    <button data-testid="assistant-copy-button">Copy</button>
                    <div role="toolbar"><button>Read aloud</button></div>
                </div>
            </article></main>
        """)
        signature = self.worker.get_assistant_response_signature(self.page)
        self.assertEqual(signature["count"], 0, signature)
        self.assertEqual(signature["last_tail"], "", signature)

    def test_accessibility_heading_and_controls_do_not_complete_empty_turn(self):
        self.page.set_content("""
            <main><article data-turn="assistant" data-testid="conversation-turn-2">
                <h6 class="sr-only">ChatGPT said:</h6>
                <div data-message-author-role="assistant"></div>
                <button data-testid="assistant-copy-button">Copy</button>
            </article></main>
        """)
        signature = self.worker.get_assistant_response_signature(self.page)
        self.assertEqual(signature["count"], 0, signature)
        self.assertEqual(signature["last_len"], 0, signature)
        self.assertEqual(signature["last_tail"], "", signature)

    def test_hidden_text_and_button_labels_are_excluded(self):
        self.page.set_content("""
            <main><div data-message-author-role="assistant">
                数学奥林匹克
                <button data-testid="assistant-copy-button">Copy</button>
                <span style="display:none">Unfinished old answer</span>
                <div data-testid="assistant-placeholder" style="visibility:hidden">Loading</div>
            </div></main>
        """)
        self.assert_response("数学奥林匹克")

    def test_data_turn_roles_exclude_user_and_composer(self):
        self.page.set_content("""
            <main>
                <article data-turn="user"><div class="markdown">chép lại nguyên văn</div></article>
                <article data-turn="assistant"><div class="markdown">数学奥林匹克</div></article>
                <form><div id="prompt-textarea" contenteditable="true">
                    <div class="message-content">Dịch sang tiếng Việt</div>
                </div></form>
            </main>
        """)
        self.assert_response("数学奥林匹克")

    def test_short_chinese_response_is_new_but_unchanged_history_is_not(self):
        self.page.set_content('<main><div id="turns"></div></main>')
        before = self.worker.get_assistant_response_signature(self.page)
        self.page.locator("#turns").evaluate("""node => {
            node.innerHTML = '<div data-message-author-role="assistant"><div class="markdown">升级版</div></div>';
        }""")
        self.assertTrue(self.worker.has_new_assistant_response(self.page, before))
        completed = self.assert_response("升级版")
        self.assertFalse(self.worker.has_new_assistant_response(self.page, completed))

    def test_user_only_turn_and_composer_are_not_a_response(self):
        self.page.set_content("""
            <main>
                <article data-turn="user"><div class="message-content">chép lại nguyên văn</div></article>
                <form><div id="prompt-textarea" contenteditable="true">
                    <div class="message-content">Dịch</div>
                </div></form>
            </main>
        """)
        signature = self.worker.get_assistant_response_signature(self.page)
        self.assertEqual(signature["count"], 0, signature)
        self.assertEqual(signature["last_len"], 0, signature)
        self.assertEqual(signature["last_tail"], "", signature)

    def test_gemini_nested_response_remains_one_response(self):
        self.page.set_content("""
            <main><model-response><message-content>
                <div class="markdown">Bản nâng cấp</div>
            </message-content></model-response></main>
        """)
        self.assert_response("Bản nâng cấp")

    def test_old_quota_warning_and_new_user_text_do_not_trigger_quota(self):
        self.page.set_content("""
            <main><div id="turns">
                <article data-turn="assistant"><div class="markdown">
                    You've hit the image generation limit.
                </div></article>
            </div></main>
        """)
        before = self.worker.get_assistant_response_signature(self.page)
        self.page.locator("#turns").evaluate("""node => {
            node.insertAdjacentHTML('beforeend',
                `<article data-turn="user"><div class="markdown">You've hit the image generation limit.</div></article>` +
                '<article data-turn="assistant"><div class="markdown">升级版</div></article>');
        }""")
        self.assertTrue(self.worker.has_new_assistant_response(self.page, before))
        self.assertIsNone(self.worker.get_generation_quota_evidence(self.page, before))

    def test_new_quota_warning_is_found_despite_assistant_controls(self):
        self.page.set_content('<main><div id="turns"></div></main>')
        before = self.worker.get_assistant_response_signature(self.page)
        self.page.locator("#turns").evaluate("""node => {
            node.innerHTML = '<article data-turn="assistant"><div data-message-author-role="assistant">' +
                `<div class="markdown">You've hit the image generation limit.</div>` +
                '<button data-testid="assistant-actions-menu" aria-label="More"><svg width="16" height="16"></svg></button>' +
                '</div></article>';
        }""")
        self.assertEqual(
            self.worker.get_generation_quota_evidence(self.page, before),
            "You've hit the image generation limit.",
        )

    def test_quota_tool_card_is_preserved_beside_markdown_follow_up(self):
        self.page.set_content('<main><div id="turns"></div></main>')
        before = self.worker.get_assistant_response_signature(self.page)
        self.page.locator("#turns").evaluate("""node => {
            node.innerHTML = '<article data-turn="assistant"><div data-message-author-role="assistant">' +
                `<div class="image-tool">You've hit the image generation limit.</div>` +
                '<div class="markdown">I can help with the text instead.</div>' +
                '</div></article>';
        }""")
        evidence = self.worker.get_generation_quota_evidence(self.page, before)
        self.assertIsNotNone(evidence)
        self.assertIn("You've hit the image generation limit.", evidence)

    def test_streaming_then_stable_text_completes_with_icon_controls(self):
        self.page.set_content('<main><div id="turns"></div></main>')
        before = self.worker.get_assistant_response_signature(self.page)
        self.page.locator("#turns").evaluate("""node => {
            node.innerHTML = '<article data-testid="conversation-turn-2" data-turn="assistant">' +
                '<div data-message-author-role="assistant"><div id="answer" class="markdown">数</div>' +
                '<button data-testid="assistant-actions-menu" aria-label="More"><svg width="16" height="16"></svg></button>' +
                '</div></article><button data-testid="stop-button">Stop generating</button>';
        }""")

        class Clock:
            now = 100

            def time(clock):
                return clock.now

            def sleep(clock, seconds):
                clock.now += seconds
                if clock.now >= 102:
                    self.page.locator("#answer").evaluate("node => node.textContent = '数学奥林匹克'")
                if clock.now >= 104:
                    self.page.evaluate("document.querySelector('[data-testid=\"stop-button\"]')?.remove()")

        clock = Clock()
        with patch.object(self.worker, "time", clock), patch.object(
            self.worker, "sleep", clock.sleep
        ), patch.object(self.worker, "wait_if_cloudflare"):
            self.assertTrue(
                self.worker.wait_assistant_response_stable(
                    self.page, before, stable_seconds=3, timeout=12
                )
            )
        self.assertGreaterEqual(clock.now, 107)
        self.assertLess(clock.now, 112)
        self.assert_response("数学奥林匹克")

    def test_rerender_gap_restarts_continuous_stability_window(self):
        self.page.set_content('<main><div id="turns"></div></main>')
        before = self.worker.get_assistant_response_signature(self.page)
        answer = '<div data-message-author-role="assistant"><div class="markdown">升级版</div></div>'
        self.page.locator("#turns").evaluate("(node, text) => node.innerHTML = text", answer)

        class Clock:
            now = 0

            def time(clock):
                return clock.now

            def sleep(clock, seconds):
                clock.now += seconds
                content = "" if 2 <= clock.now < 4 else answer
                self.page.locator("#turns").evaluate("(node, text) => node.innerHTML = text", content)

        clock = Clock()
        with patch.object(self.worker, "time", clock), patch.object(
            self.worker, "sleep", clock.sleep
        ), patch.object(self.worker, "wait_if_cloudflare"):
            self.assertTrue(
                self.worker.wait_assistant_response_stable(
                    self.page, before, stable_seconds=3, timeout=12
                )
            )
        self.assertGreaterEqual(clock.now, 7)
        self.assertLess(clock.now, 12)


if __name__ == "__main__":
    unittest.main()
