"""Upload attachment regressions using real Chromium, without a live account."""
import base64
import importlib.util
import os
from pathlib import Path
import sys
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from test_image_results import image_bytes, image_url


class UploadAttachmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "upload_worker", PROJECT_ROOT / "run_chatgpt_batch.py"
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

    def show(self, html):
        self.page.set_content(html)
        self.page.wait_for_function("Array.from(document.images).every(img => img.complete)")

    def wait_attached(self):
        # Advance only the worker's polling clock; DOM checks still use Chromium.
        now = [0]

        def advance(seconds):
            now[0] += seconds

        with patch.object(self.worker.time, "time", side_effect=lambda: now[0]), \
             patch.object(self.worker, "sleep", side_effect=advance), \
             patch.object(self.worker, "wait_if_cloudflare"):
            return self.worker.wait_upload_attached(self.page, timeout=3)

    def test_preview_in_unnamed_composer_wrapper_is_recognized(self):
        self.show(f"""
            <main>
                <div class="flex flex-col gap-2">
                    <div class="flex gap-2"><img src="{image_url(size=(90, 110))}"></div>
                    <div class="flex"><div class="grow"><div class="relative">
                        <div id="prompt-textarea" contenteditable="true"></div>
                    </div></div></div>
                    <button aria-label="Send prompt">Send</button>
                </div>
            </main>
        """)
        self.assertTrue(self.wait_attached())

    def test_icon_words_inside_valid_png_base64_are_not_icon_url_hints(self):
        # Insert a valid private ancillary PNG chunk, aligned so that the
        # encoded payload contains the word that triggered the real rejection.
        for word in ('emojiAAA', 'avatarAA'):
            with self.subTest(word=word):
                png = image_bytes()
                padding = (-(len(png) - 12 + 8)) % 3
                payload = b'\0' * padding + base64.b64decode(word)
                chunk = b'raNd' + payload
                chunk = struct.pack('>I', len(payload)) + chunk + struct.pack('>I', zlib.crc32(chunk))
                png = png[:-12] + chunk + png[-12:]
                src = 'data:image/png;base64,' + base64.b64encode(png).decode()
                self.assertIn(word.lower(), src.lower())
                self.show(f'<form><img src="{src}"><div id="prompt-textarea" contenteditable="true"></div></form>')
                self.assertEqual(self.page.evaluate('document.images[0].naturalWidth'), 320)
                self.assertTrue(self.wait_attached())

    def test_file_input_upload_proceeds_to_sending_transcription_prompt(self):
        self.show("""
            <main><div class="flex flex-col gap-2">
                <input type="file" accept="image/*" style="display:none">
                <div id="previews"></div>
                <div><div><div id="prompt-textarea" contenteditable="true"></div></div></div>
                <button aria-label="Send prompt">Send</button>
            </div></main>
            <script>
                document.querySelector('input').addEventListener('change', event => {
                    const img = document.createElement('img');
                    img.src = URL.createObjectURL(event.target.files[0]);
                    document.querySelector('#previews').appendChild(img);
                });
                document.querySelector('button').addEventListener('click', () => {
                    window.sentText = document.querySelector('#prompt-textarea').textContent;
                    window.sentFiles = document.querySelector('input').files.length;
                    document.querySelector('#prompt-textarea').textContent = '';
                });
            </script>
        """)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / '29_029.jpg'
            image.write_bytes(image_bytes(fmt='JPEG', size=(90, 110)))
            with patch.object(self.worker, 'sleep'):
                self.worker.upload_image(self.page, image, service='chatgpt')
            self.page.wait_for_function("document.querySelector('#previews img')?.naturalWidth > 0")
            self.assertTrue(self.wait_attached())
            with patch.object(self.worker, 'sleep'), patch.object(self.worker, 'wait_if_cloudflare'):
                self.assertTrue(self.worker.send_prompt(self.page, self.worker.PROMPT_CHEP_LAI))
        self.assertEqual(self.page.evaluate('window.sentText'), self.worker.PROMPT_CHEP_LAI)
        self.assertEqual(self.page.evaluate('window.sentFiles'), 1)

    def test_legacy_form_and_gemini_composers_still_work(self):
        for composer in (
            '<form>{image}<div id="prompt-textarea" contenteditable="true"></div></form>',
            '<div class="input-area-container">{image}<rich-textarea>'
            '<div class="ql-editor" contenteditable="true"></div></rich-textarea></div>',
        ):
            with self.subTest(composer=composer):
                self.show(composer.format(image=f'<img src="{image_url()}">'))
                self.assertTrue(self.wait_attached())

    def test_deep_unnamed_wrappers_do_not_need_composer_class_names(self):
        self.show('<main><div><img src="' + image_url() + '">' +
                  '<div>' * 8 + '<div id="prompt-textarea" contenteditable="true"></div>' +
                  '</div>' * 8 + '</div></main>')
        self.assertTrue(self.wait_attached())

    def test_hidden_stale_editor_does_not_hide_visible_attachment(self):
        self.show(f"""
            <div id="prompt-textarea" contenteditable="true" style="display:none"></div>
            <div class="input-area-container"><img src="{image_url()}">
                <rich-textarea><div class="ql-editor" contenteditable="true"></div></rich-textarea>
            </div>
        """)
        self.assertTrue(self.wait_attached())

    def test_history_images_are_not_attachments(self):
        for marker in (
            'data-message-author-role="user"', 'data-message-author-role="assistant"',
            'data-testid="conversation-turn-1"', 'data-content-search-turn-key="fallback-turn-0"',
            'data-content-search-unit-key="fallback-turn-0:0:user"',
        ):
            with self.subTest(marker=marker):
                self.show(f"""
                    <main><div class="flex flex-col">
                        <div {marker}><img src="{image_url()}"></div>
                        <div><div id="prompt-textarea" contenteditable="true"></div></div>
                    </div></main>
                """)
                with self.assertRaisesRegex(Exception, 'Không xác nhận được ảnh'):
                    self.wait_attached()

    def test_sidebar_image_does_not_count_as_upload(self):
        self.show(f"""
            <div><aside><img src="{image_url()}"></aside>
                <div><div id="prompt-textarea" contenteditable="true"></div></div>
            </div>
        """)
        with self.assertRaisesRegex(Exception, 'Không xác nhận được ảnh'):
            self.wait_attached()

    def test_named_composer_boundary_does_not_include_images_outside_it(self):
        for boundary in ('form', 'div id="composer-background"', 'div data-testid="composer"'):
            with self.subTest(boundary=boundary):
                tag = boundary.split()[0]
                self.show(f"""
                    <main><div><img src="{image_url()}">
                        <{boundary}><div id="prompt-textarea" contenteditable="true"></div></{tag}>
                    </div></main>
                """)
                with self.assertRaisesRegex(Exception, 'Không xác nhận được ảnh'):
                    self.wait_attached()

    def test_hidden_broken_and_icon_images_are_not_attachments(self):
        for preview in (
            f'<img style="visibility:hidden" src="{image_url()}">',
            f'<div style="display:none"><img src="{image_url()}"></div>',
            '<img width="90" height="110" src="data:image/png;base64,invalid">',
            f'<img width="24" height="24" src="{image_url()}">',
            '<img width="90" height="110" src="data:image/svg+xml,'
            '%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'90\' height=\'110\'%3E%3C/svg%3E">',
        ):
            with self.subTest(preview=preview[:60]):
                self.show(f'<form>{preview}<div id="prompt-textarea" contenteditable="true"></div></form>')
                with self.assertRaisesRegex(Exception, 'Không xác nhận được ảnh'):
                    self.wait_attached()

    def test_captured_prosemirror_composer_layout_without_editor_id(self):
        self.show(f"""
            <main><form class="relative flex flex-col gap-2"><div class="contents">
                <div class="ComposerLayoutRoot-XCKS7O" role="presentation">
                    <div class="relative w-full flex-col gap-2 flex"><div class="ComposerModeSurface-lVLm7j">
                        <div class="ComposerLayoutBody-uBBf1A">
                            <div class="flex flex-wrap items-end gap-3 p-1">
                                <div class="composer-attachment-surface" role="button">
                                    <span class="composer-attachment-surface">
                                        <img class="size-full object-cover" width="122" height="122"
                                             src="{image_url(size=(1237, 1882))}">
                                    </span>
                                </div>
                            </div>
                            <div class="ComposerLayoutFooter-_8IVRO"><div class="AdaptiveFooterInput-zji599">
                                <div class="contents"><div class="ComposerLayoutInput-KwIAr_">
                                    <div role="presentation"><div class="ProseMirror" role="textbox"
                                         contenteditable="true" style="width:732px;height:26px"></div></div>
                                </div></div>
                            </div></div>
                        </div>
                    </div></div>
                </div>
            </div></form></main>
        """)
        self.assertTrue(self.wait_attached())
