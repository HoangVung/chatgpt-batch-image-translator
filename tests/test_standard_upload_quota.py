"""Standard-worker upload quota regressions using offline Chromium fixtures."""
import unittest
from unittest.mock import patch
import test_books34_upload_quota as fixtures
import run_chatgpt_batch as worker

NOTICE = 'Get Plus for more uploads\nOr wait 23 hours to upload again'

class StandardUploadQuotaTests(unittest.TestCase):
    setUpClass = fixtures.ComposerUploadQuotaTests.__dict__['setUpClass']
    tearDownClass = fixtures.ComposerUploadQuotaTests.__dict__['tearDownClass']
    setUp = fixtures.ComposerUploadQuotaTests.setUp
    show = fixtures.ComposerUploadQuotaTests.show
    show_quota_menu = fixtures.ComposerUploadQuotaTests.show_quota_menu

    def test_menu_quota_becomes_upload_quota_without_submitting(self):
        self.show_quota_menu()
        self.page.locator('#quota-row').evaluate("el=>el.innerHTML='<span>Get Plus for more uploads</span><div>Or wait 23 hours to upload again</div>'")
        with patch.object(worker, 'wait_if_cloudflare'), self.assertRaises(worker.QuotaExhaustedError) as caught:
            worker.upload_image(self.page, self.image, service='chatgpt')
        error = caught.exception
        self.assertEqual(error.quota_kind, 'upload')
        self.assertIn('Or wait 23 hours to upload again', error.evidence)
        self.assertEqual(error.detected_at, error.__cause__.detected_at)
        self.assertEqual(self.page.evaluate('window.sent'), 0)
        self.assertEqual(self.page.evaluate('window.upgradeClicks'), 0)

    def test_quota_after_file_selection_stops_attachment_wait(self):
        self.show(inside='<input id="upload-files" type="file" style="display:none"><div role="alert" id="quota" style="display:none"></div>',
                  script='document.querySelector("#upload-files").onchange=()=>{const el=document.querySelector("#quota");el.textContent="Get Plus for more uploads. Or wait 23 hours to upload again";el.style.display="block";};')
        with patch.object(worker, 'wait_if_cloudflare'), patch.object(worker, 'SERVICE', 'chatgpt'):
            worker.upload_image(self.page, self.image, service='chatgpt')
            with self.assertRaises(worker.QuotaExhaustedError) as caught:
                worker.wait_upload_attached(self.page, timeout=2)
        self.assertEqual(caught.exception.quota_kind, 'upload')
        self.assertIn('23 hours', caught.exception.evidence)
        self.assertEqual(self.page.evaluate('window.sent'), 0)

    def test_history_sidebar_and_hidden_notice_do_not_block_upload(self):
        self.show(inside='<input id="upload-files" type="file" style="display:none"><div role="alert" style="display:none">'+NOTICE+'</div>',
                  outside='<aside>'+NOTICE+'</aside><div data-message-author-role="assistant">'+NOTICE+'</div>')
        with patch.object(worker, 'wait_if_cloudflare'):
            worker.upload_image(self.page, self.image, service='chatgpt')
        self.assertEqual(self.page.locator('#upload-files').evaluate('el=>el.files.length'), 1)
        self.assertEqual(self.page.evaluate('window.sent'), 0)

    def test_gemini_upload_does_not_use_chatgpt_composer(self):
        self.show(inside='<input type="file" id="upload-files" style="display:none">')
        with patch.object(worker.composer, 'upload') as upload, patch.object(worker, 'sleep'):
            worker.upload_image(self.page, self.image, service='gemini')
        upload.assert_not_called()
        self.assertEqual(self.page.locator('#upload-files').evaluate('el=>el.files.length'), 1)

    def test_twenty_three_hour_reset_is_preserved(self):
        from desktop.quota_limits import reset_delay_seconds
        self.assertEqual(reset_delay_seconds(NOTICE), 23 * 3600)

if __name__ == '__main__':
    unittest.main()
