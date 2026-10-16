"""Upload quota notices must stop upload and enter the account fallback path."""
import base64
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, sentinel

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import books34_composer as composer
import run_chatgpt_batch_books34 as worker


NOTICE = "Get Plus for more uploads\nOr wait 18 hours to upload again"
NOTICE_ROW = (
    '<div role="menuitem" aria-disabled="true" id="quota-row">'
    '<span>Get Plus for more uploads</span>'
    '<div>Or wait 18 hours to upload again</div></div>'
)


class ComposerUploadQuotaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / "sample.png"
        self.image.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aHfcAAAAASUVORK5CYII="
        ))

    def show(self, inside="", outside="", script=""):
        self.page.set_content(
            '<main><form id="current-form"><div id="composer-background">'
            '<div id="prompt-textarea" contenteditable="true" style="height:40px;width:400px"></div>'
            + inside + '</div></form></main>' + outside
            + '<script>window.attachClicks=0;window.upgradeClicks=0;window.sent=0;'
            'document.querySelector("form").onsubmit=e=>{e.preventDefault();window.sent++;};'
            + script + '</script>'
        )

    def menu_handle(self):
        handle = self.page.query_selector("#attachment-menu")
        self.addCleanup(handle.dispose)
        return handle

    def assert_notice(self, evidence):
        self.assertIn("Get Plus for more uploads", evidence)
        self.assertIn("Or wait 18 hours to upload again", evidence)

    def show_quota_menu(self, *, modal=False, controlled=True):
        controls = ' aria-controls="attachment-menu"' if controlled else ""
        self.show(
            inside='<button type="button" id="composer-plus-btn" aria-label="Add files and more"'
                   + controls + '>+</button>'
                   '<input id="blocked-upload" type="file" disabled style="display:none">',
            outside='<div role="menu" id="attachment-menu" style="display:none">'
                    + NOTICE_ROW
                    + '<button type="button" onclick="window.upgradeClicks++">Upgrade to Plus</button>'
                    '<div role="menuitem">Create image</div></div>',
            script='document.querySelector("#composer-plus-btn").onclick=()=>{'
                   'window.attachClicks++;document.querySelector("#attachment-menu").style.display="block";'
                   + ('document.body.style.pointerEvents="none";'
                      'document.querySelector("#attachment-menu").style.pointerEvents="auto";'
                      if modal else '') + '};'
        )

    def test_exact_screenshot_disabled_row_preserves_reset_evidence(self):
        self.show(outside='<div role="menu" id="attachment-menu">' + NOTICE_ROW
                  + '<div role="menuitem">Web search</div></div>')
        evidence = composer.get_upload_quota_evidence(self.page, self.menu_handle())
        self.assert_notice(evidence)
        self.assertNotIn("Web search", evidence)

    def test_current_composer_notice_prevents_setting_even_available_input(self):
        self.show(inside='<div role="alert">' + NOTICE.replace("\n", "<br>") + '</div>'
                  '<input type="file" id="upload-files" style="display:none">')
        before = time.time()
        with self.assertRaises(composer.UploadQuotaError) as caught:
            composer.upload(self.page, self.image, timeout=2)
        self.assert_notice(caught.exception.evidence)
        self.assertGreaterEqual(caught.exception.detected_at, before)
        self.assertLessEqual(caught.exception.detected_at, time.time())
        self.assertEqual(self.page.locator("#upload-files").evaluate("el=>el.files.length"), 0)
        self.assertEqual(self.page.evaluate("window.sent"), 0)

    def test_visible_upload_alert_outside_composer_is_detected(self):
        self.show(outside='<div role="alert">File upload limit reached. Try again in 2 hours.</div>')
        self.assertEqual(composer.get_upload_quota_evidence(self.page),
                         "File upload limit reached. Try again in 2 hours.")

    def test_upload_limit_reported_after_file_selection_enters_fallback(self):
        self.show(inside='<input type="file" id="upload-files" style="display:none">',
                  script='document.querySelector("#upload-files").onchange=()=>{'
                         'const alert=document.createElement("div");alert.role="alert";'
                         'alert.textContent="File upload limit reached. Try again in 2 hours.";'
                         'document.body.append(alert);};')
        composer.upload(self.page, self.image, timeout=2)
        self.assertEqual(self.page.locator("#upload-files").evaluate("el=>el.files.length"), 1)
        with patch.object(worker, "wait_if_cloudflare"), \
                patch.object(worker.composer, "diagnostic") as diagnostic, \
                patch.object(worker, "print"):
            with self.assertRaises(worker.QuotaExhaustedError) as caught:
                worker.wait_upload_attached(self.page, timeout=2)
        self.assertEqual(caught.exception.evidence,
                         "File upload limit reached. Try again in 2 hours.")
        self.assertEqual(caught.exception.quota_kind, "upload")
        diagnostic.assert_not_called()

    def test_newly_opened_quota_menu_exits_without_reopening_or_upgrading(self):
        self.show_quota_menu(controlled=False)
        started = time.monotonic()
        with self.assertRaises(composer.UploadQuotaError) as caught:
            composer.upload(self.page, self.image, timeout=12)
        self.assert_notice(caught.exception.evidence)
        self.assertLess(time.monotonic() - started, 8)
        self.assertEqual(self.page.evaluate("window.attachClicks"), 1)
        self.assertEqual(self.page.evaluate("window.upgradeClicks"), 0)
        self.assertEqual(self.page.locator("#blocked-upload").evaluate("el=>el.files.length"), 0)
        self.assertEqual(self.page.evaluate("window.sent"), 0)

    def test_quota_menu_detected_when_modal_disables_editor(self):
        self.show_quota_menu(modal=True)
        with self.assertRaises(composer.UploadQuotaError) as caught:
            composer.upload(self.page, self.image, timeout=12)
        self.assert_notice(caught.exception.evidence)
        self.assertEqual(self.page.evaluate("window.attachClicks"), 1)
        self.assertEqual(self.page.evaluate("window.upgradeClicks"), 0)

    def test_already_open_owned_menu_is_detected_before_input_or_ready_check(self):
        for modal in (False, True):
            with self.subTest(modal=modal):
                self.show_quota_menu(modal=modal)
                self.page.locator("#composer-plus-btn").click()
                self.page.locator("#blocked-upload").evaluate("el=>el.disabled=false")
                with self.assertRaises(composer.UploadQuotaError) as caught:
                    composer.upload(self.page, self.image, timeout=2)
                self.assert_notice(caught.exception.evidence)
                self.assertEqual(self.page.evaluate("window.attachClicks"), 1)
                self.assertEqual(self.page.locator("#blocked-upload").evaluate("el=>el.files.length"), 0)
                self.assertEqual(self.page.evaluate("window.upgradeClicks"), 0)

    def test_unrelated_alert_in_nested_menu_is_not_current_composer_quota(self):
        self.show(inside='<div role="menu"><div role="alert">' + NOTICE + '</div></div>',
                  outside='<div role="dialog"><div role="alert">' + NOTICE + '</div></div>')
        self.assertFalse(composer.get_upload_quota_evidence(self.page))

    def test_history_sidebar_hidden_alerts_and_editor_text_are_not_quota(self):
        self.show(
            inside='<div role="alert" style="display:none">' + NOTICE + '</div>',
            outside='<article data-message-author-role="assistant"><div role="alert">'
                    + NOTICE + '</div></article><aside><div role="alert">' + NOTICE
                    + '</div></aside><nav><div role="alert">' + NOTICE + '</div></nav>'
                    '<div hidden><div role="alert">' + NOTICE + '</div></div>'
        )
        self.page.locator("#prompt-textarea").fill(NOTICE)
        self.assertFalse(composer.get_upload_quota_evidence(self.page))

    def test_hidden_quota_within_selected_menu_is_not_detected(self):
        self.show(outside='<div role="menu" id="attachment-menu"><div style="display:none">'
                  + NOTICE_ROW + '</div><div role="menuitem">Add photos &amp; files</div></div>')
        self.assertFalse(composer.get_upload_quota_evidence(self.page, self.menu_handle()))

    def test_generic_get_plus_offer_is_not_upload_quota(self):
        self.show(inside='<div>Get Plus</div>',
                  outside='<div role="menu" id="attachment-menu"><button>Get Plus</button>'
                          '<div role="menuitem">Add photos &amp; files</div></div>')
        self.assertFalse(composer.get_upload_quota_evidence(self.page, self.menu_handle()))

    def test_unselected_visible_menu_notice_is_ignored(self):
        self.show(outside='<div role="menu" id="unrelated-menu">' + NOTICE_ROW + '</div>'
                  '<div role="menu" id="attachment-menu"><div role="menuitem">Add files</div></div>')
        self.assertFalse(composer.get_upload_quota_evidence(self.page))
        self.assertFalse(composer.get_upload_quota_evidence(self.page, self.menu_handle()))

    def test_existing_unrelated_quota_menu_does_not_block_valid_composer_input(self):
        self.show(inside='<input type="file" id="upload-files" style="display:none">',
                  outside='<div role="menu" id="unrelated-menu">' + NOTICE_ROW + '</div>')
        composer.upload(self.page, self.image, timeout=2)
        self.assertEqual(self.page.locator("#upload-files").evaluate("el=>el.files.length"), 1)
        self.assertEqual(self.page.evaluate("window.sent"), 0)


    def test_unlabelled_attachment_panel_without_controls_detects_quota(self):
        self.show_quota_menu(controlled=False)
        self.page.locator('#attachment-menu').evaluate('el=>el.removeAttribute("role")')
        self.page.locator('#quota-row').evaluate('el=>el.textContent="Get Plus for more uploads. Or wait 23 hours to upload again"')
        with self.assertRaises(composer.UploadQuotaError) as caught:
            composer.upload(self.page, self.image, timeout=12)
        self.assertIn('23 hours', caught.exception.evidence)
        self.assertEqual(self.page.evaluate('window.attachClicks'), 1)
        self.assertEqual(self.page.evaluate('window.upgradeClicks'), 0)
        self.assertEqual(self.page.evaluate('window.sent'), 0)

    def test_already_open_unlabelled_panel_is_reobserved_after_toggle(self):
        self.show_quota_menu(controlled=False)
        self.page.locator('#attachment-menu').evaluate('el=>el.removeAttribute("role")')
        self.page.evaluate("""() => {
            const button=document.querySelector('#composer-plus-btn'), panel=document.querySelector('#attachment-menu');
            button.onclick=()=>{window.attachClicks++;const open=panel.style.display==='none';panel.style.display=open?'block':'none';button.setAttribute('aria-expanded',String(open));};
        }""")
        self.page.locator('#composer-plus-btn').click()
        with self.assertRaises(composer.UploadQuotaError) as caught:
            composer.upload(self.page, self.image, timeout=12)
        self.assert_notice(caught.exception.evidence)
        self.assertEqual(self.page.evaluate('window.attachClicks'), 3)
        self.assertEqual(self.page.evaluate('window.sent'), 0)

    def test_preexisting_unlabelled_notice_does_not_block_valid_upload(self):
        self.show(inside='<input type="file" id="upload-files" style="display:none">',
                  outside='<div id="unrelated-panel">'+NOTICE_ROW+'</div>')
        composer.upload(self.page, self.image, timeout=2)
        self.assertEqual(self.page.locator('#upload-files').evaluate('el=>el.files.length'), 1)
        self.assertEqual(self.page.evaluate('window.sent'), 0)


class WorkerUploadQuotaMappingTests(unittest.TestCase):
    def test_upload_quota_reaches_existing_account_fallback_with_original_evidence_and_time(self):
        detected_at = 1791607860.0
        error = composer.UploadQuotaError(NOTICE, detected_at=detected_at)
        with patch.object(worker, "wait_if_cloudflare"), \
                patch.object(worker.composer, "upload", side_effect=error), \
                patch.object(worker.composer, "diagnostic") as diagnostic, \
                patch.object(worker, "print"):
            with self.assertRaises(worker.QuotaExhaustedError) as caught:
                worker.upload_image(sentinel.page, Path("sample.png"), service="chatgpt")
        self.assertEqual(caught.exception.evidence, NOTICE)
        self.assertEqual(caught.exception.detected_at, detected_at)
        self.assertEqual(caught.exception.quota_kind, "upload")
        diagnostic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
