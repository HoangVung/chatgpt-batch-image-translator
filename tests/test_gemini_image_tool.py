"""Gemini tool selection and prompt ordering in local Chromium; no live account."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


class GeminiImageToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        spec = importlib.util.spec_from_file_location(
            "gemini_image_worker", PROJECT_ROOT / "run_chatgpt_batch.py"
        )
        cls.worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.worker)
        cls.playwright = sync_playwright().start()
        options = {"headless": True}
        if os.environ.get("BATCH_TEST_BROWSER"):
            options["executable_path"] = os.environ["BATCH_TEST_BROWSER"]
        try:
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
        self.sleep = patch.object(
            self.worker, "sleep", side_effect=lambda _: self.page.wait_for_timeout(10)
        )
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def show(self, tools="Công cụ", image="Tạo ảnh", role="menuitem", chip="",
             selection_works=True, disabled=False, delay=0):
        self.page.set_content("""
            <style>input-area-v2, rich-textarea {display:block}
                [contenteditable] {min-height:40px; width:400px}</style>
            <main><user-query id="original">Ảnh gốc</user-query>
                <model-response id="translation">Bản dịch tiếng Việt
                    <button aria-pressed="true">Images</button>
                </model-response></main>
            <input-area-v2>
                <rich-textarea><div class="ql-editor" contenteditable="true"></div></rich-textarea>
                <button id="tools"></button><span id="chips"></span>
                <button aria-label="Send message" id="send">Gửi</button>
            </input-area-v2>
            <div role="menu" id="menu" hidden><button id="image"></button></div>
            <script>
                window.events = [];
                window.sent = [];
                const prompt = document.querySelector('.ql-editor');
                prompt.addEventListener('input', () => {
                    if (prompt.textContent.trim()) events.push('fill');
                });
                document.querySelector('#tools').onclick = () => {
                    events.push('tools');
                    document.querySelector('#menu').hidden = false;
                };
                document.querySelector('#image').onclick = () => {
                    events.push('image');
                    if (!window.selectionWorks) return;
                    setTimeout(() => {
                        document.querySelector('#chips').innerHTML = window.chip;
                        document.querySelector('#menu').hidden = true;
                        events.push('selected');
                    }, window.selectionDelay);
                };
                document.querySelector('#send').onclick = () => {
                    events.push('send');
                    sent.push(prompt.textContent.trim());
                    prompt.textContent = '';
                };
            </script>
        """)
        self.page.evaluate("""(config) => {
            const tools = document.querySelector('#tools');
            tools.textContent = config.tools;
            tools.setAttribute('aria-label', config.tools);
            const image = document.querySelector('#image');
            image.textContent = config.image;
            image.setAttribute('role', config.role);
            image.disabled = config.disabled;
            window.chip = config.chip || '<button class="tool-chip" aria-pressed="true">' +
                config.image + '<mat-icon>close</mat-icon></button>';
            window.selectionWorks = config.selectionWorks;
            window.selectionDelay = config.delay;
        }""", {"tools": tools, "image": image, "role": role, "chip": chip,
                 "selectionWorks": selection_works, "disabled": disabled, "delay": delay})

    def create(self, service="gemini"):
        with patch.object(self.worker, "SERVICE", service), \
             patch.object(self.worker, "is_generating", return_value=True), \
             patch.object(self.worker, "wait_image_generation_finished_or_image_ready",
                          return_value="generated-image"):
            return self.worker.try_create_image(self.page, [])

    def test_vietnamese_tool_selected_before_real_prompt_fill_and_send(self):
        self.show(delay=50)
        self.assertEqual(self.create(), "generated-image")
        events = self.page.evaluate("events")
        self.assertLess(events.index("selected"), events.index("fill"))
        self.assertLess(events.index("fill"), events.index("send"))
        self.assertEqual(self.page.evaluate("sent"), [self.worker.PROMPT_TAO_ANH_GEMINI])
        self.assertEqual(self.page.locator("#original").text_content(), "Ảnh gốc")
        self.assertIn("Bản dịch tiếng Việt", self.page.locator("#translation").text_content())

    def test_english_overlay_button_and_deselect_chip(self):
        self.show(tools="Tools", image="Create images", role="button",
                  chip='<button aria-label="Deselect Images">Images</button>')
        self.create()
        self.assertTrue(self.worker.gemini_image_tool_selected(self.page))
        self.assertEqual(self.page.evaluate("events.slice(0, 3)"), ["tools", "image", "selected"])

    def test_already_selected_tool_is_preserved(self):
        self.show()
        self.page.locator("#chips").evaluate(
            "el => el.innerHTML = '<button class=tool-chip aria-pressed=true>Tạo hình ảnh</button>'"
        )
        self.worker.ensure_gemini_image_tool(self.page)
        self.worker.ensure_gemini_image_tool(self.page)
        self.assertEqual(self.page.evaluate("events"), [])

    def test_direct_tool_toggle_is_selected_before_send(self):
        self.show(tools="Create images", image="Create images")
        self.page.locator("#tools").evaluate("""el => {
            el.setAttribute('aria-pressed', 'false');
            el.onclick = () => {
                el.setAttribute('aria-pressed', 'true');
                events.push('selected');
            };
        }""")
        self.create()
        self.assertEqual(self.page.evaluate("events[0]"), "selected")

    def test_history_hidden_chip_and_open_menu_are_not_selection(self):
        self.show()
        self.page.locator("#chips").evaluate(
            "el => el.innerHTML = '<button class=tool-chip hidden>Images</button>'"
        )
        self.page.locator("#menu").evaluate("""el => {
            el.hidden = false;
            el.querySelector('button').setAttribute('aria-selected', 'true');
        }""")
        self.assertFalse(self.worker.gemini_image_tool_selected(self.page))

    def assert_no_send_on_failure(self):
        ensure = self.worker.ensure_gemini_image_tool
        with patch.object(self.worker, "ensure_gemini_image_tool",
                          side_effect=lambda page: ensure(page, timeout=0.15)):
            with self.assertRaisesRegex(RuntimeError, "chưa gửi prompt"):
                self.create()
        self.assertEqual(self.page.evaluate("sent"), [])
        self.assertNotIn("fill", self.page.evaluate("events"))
        self.assertEqual(self.worker.get_prompt_text(self.page), "")

    def test_click_without_active_tool_confirmation_does_not_send(self):
        self.show(selection_works=False)
        self.assert_no_send_on_failure()

    def test_unavailable_image_tool_does_not_send(self):
        self.show(disabled=True)
        self.assert_no_send_on_failure()

    def test_missing_tools_menu_does_not_send(self):
        self.show()
        self.page.locator("#tools").evaluate("el => el.remove()")
        self.assert_no_send_on_failure()

    def test_chatgpt_keeps_existing_prompt_and_skips_gemini_selection(self):
        self.show()
        with patch.object(self.worker, "ensure_gemini_image_tool") as select_tool:
            self.create(service="chatgpt")
        select_tool.assert_not_called()
        self.assertEqual(self.page.evaluate("sent"), [self.worker.PROMPT_TAO_ANH])
        self.assertNotIn("tools", self.page.evaluate("events"))

    def test_ensure_gemini_normal_chat_deselects_tool_chip(self):
        self.show()
        self.page.locator("#chips").evaluate("""el => {
            el.innerHTML = '<button class="tool-chip" aria-pressed="true" aria-label="Bỏ chọn Tạo ảnh">Tạo ảnh<mat-icon>close</mat-icon></button>';
            el.querySelector('button').onclick = () => { el.innerHTML = ''; };
        }""")
        self.assertTrue(self.worker.gemini_image_tool_selected(self.page))
        self.worker.ensure_gemini_normal_chat(self.page)
        self.assertFalse(self.worker.gemini_image_tool_selected(self.page))


if __name__ == "__main__":
    unittest.main()
