"""Books 3/4 upload controls, exercised in a real browser without an account."""
import base64
import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import books34_composer as composer


class ComposerUploadTests(unittest.TestCase):
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

    def show(self, inside="", siblings="", outside="", script="", editor=True):
        editor_html = ('<div id="prompt-textarea" contenteditable="true" '
                       'style="height:40px;width:400px"></div>') if editor else ""
        self.page.set_content(
            '<main><form id="current-form"><div id="composer-background">'
            + editor_html + inside
            + '<button type="submit" data-testid="send-button">Send</button>'
            + '</div>' + siblings + '</form></main>' + outside
            + '<script>window.sent=0;window.wrongMenuClicks=0;'
            + 'document.addEventListener("submit",event=>{event.preventDefault();window.sent++;});'
            + 'document.querySelector("[data-testid=send-button]").addEventListener("click",()=>window.sent++);'
            + script + '</script>'
        )

    def upload(self, timeout=3):
        composer.upload(self.page, self.image, timeout=timeout)
        self.assertEqual(self.page.evaluate("window.sent"), 0)

    def file_count(self, selector):
        return self.page.locator(selector).evaluate("el => el.files.length")

    def assert_rejected_without_upload(self, selector):
        with self.assertRaises(RuntimeError):
            self.upload(timeout=0.5)
        self.assertEqual(self.file_count(selector), 0)
        self.assertEqual(self.page.evaluate("window.sent"), 0)

    def test_sibling_input_in_current_form_outside_named_composer(self):
        self.show(siblings='<input type="file" id="selected" style="display:none">')
        self.assertEqual(composer.inspect(self.page)["reason"], "ready")
        self.upload()
        self.assertEqual(self.file_count("#selected"), 1)

    def test_portal_input_explicitly_associated_with_current_form(self):
        self.show(outside='<input type="file" id="selected" form="current-form" style="display:none">')
        self.upload()
        self.assertEqual(self.file_count("#selected"), 1)

    def test_label_in_composer_associates_portal_input(self):
        self.show(inside='<label for="selected">Attach files</label>',
                  outside='<input type="file" id="selected" style="display:none">')
        self.upload()
        self.assertEqual(self.file_count("#selected"), 1)

    def test_control_in_composer_associates_portal_input(self):
        self.show(inside='<button type="button" aria-controls="selected">Attach files</button>',
                  outside='<input type="file" id="selected" style="display:none">')
        self.upload()
        self.assertEqual(self.file_count("#selected"), 1)

    def test_known_portal_input_requires_active_editor(self):
        self.show(outside='<input type="file" id="upload-files" style="display:none">', editor=False)
        self.assert_rejected_without_upload("#upload-files")

    def test_unrelated_global_image_picker_is_not_used(self):
        self.show(outside='<input type="file" id="unrelated" accept="image/*" style="display:none">')
        self.assert_rejected_without_upload("#unrelated")

    def test_unrelated_input_does_not_steal_current_composer_upload(self):
        self.show(siblings='<input type="file" id="selected" style="display:none">',
                  outside='<aside><input type="file" id="unrelated" accept="image/*"></aside>')
        self.upload()
        self.assertEqual(self.file_count("#selected"), 1)
        self.assertEqual(self.file_count("#unrelated"), 0)

    def test_direct_attachment_chooser_can_create_input_lazily(self):
        self.show(
            inside='<button type="button" data-testid="composer-plus-btn" aria-label="Add files and more">+</button>',
            script='document.querySelector("[data-testid=composer-plus-btn]").onclick=()=>{'
                   'const input=document.createElement("input");input.type="file";input.id="selected";'
                   'input.style.display="none";document.body.append(input);input.click();};'
        )
        self.upload()
        self.assertEqual(self.file_count("#selected"), 1)

    def show_menu_chooser(self, controlled):
        controls = ' aria-controls="attachment-menu"' if controlled else ""
        self.show(
            inside='<button type="button" data-testid="composer-plus-btn" aria-label="Add files and more"'
                   + controls + '>+</button>',
            outside='<div role="menu" id="unrelated-menu"><button type="button" role="menuitem" '
                    'onclick="window.wrongMenuClicks++">Add photos &amp; files</button></div>'
                    '<div role="menu" id="attachment-menu" style="display:none">'
                    '<button type="button" role="menuitem" id="upload-local">Add photos &amp; files</button></div>',
            script='document.querySelector("[data-testid=composer-plus-btn]").onclick=()=>{'
                   'document.querySelector("#attachment-menu").style.display="block";};'
                   'document.querySelector("#upload-local").onclick=()=>{'
                   'const input=document.createElement("input");input.type="file";input.id="selected";'
                   'input.style.display="none";document.body.append(input);input.click();};'
        )

    def test_controlled_portal_menu_opens_local_file_chooser(self):
        self.show_menu_chooser(controlled=True)
        self.upload()
        self.assertEqual(self.file_count("#selected"), 1)
        self.assertEqual(self.page.evaluate("window.wrongMenuClicks"), 0)

    def test_newly_visible_menu_is_used_without_clicking_existing_menu(self):
        self.show_menu_chooser(controlled=False)
        self.upload()
        self.assertEqual(self.file_count("#selected"), 1)
        self.assertEqual(self.page.evaluate("window.wrongMenuClicks"), 0)

    def test_modal_menu_remains_usable_when_background_editor_is_disabled(self):
        self.show_menu_chooser(controlled=True)
        self.page.evaluate("""() => {
            const trigger = document.querySelector('[data-testid=composer-plus-btn]');
            const original = trigger.onclick;
            trigger.onclick = () => {
                original();
                document.body.style.pointerEvents = 'none';
                document.querySelector('#attachment-menu').style.pointerEvents = 'auto';
            };
        }""")
        self.upload()
        self.assertEqual(self.file_count("#selected"), 1)
        self.assertEqual(self.page.evaluate("window.wrongMenuClicks"), 0)

    def test_inserting_unrelated_input_after_probe_does_not_change_upload_target(self):
        self.show(siblings='<input type="file" id="selected" style="display:none">')
        evaluate_handle = self.page.evaluate_handle
        inserted = []

        def hydrate_after_probe(expression, *args, **kwargs):
            result = evaluate_handle(expression, *args, **kwargs)
            if expression.endswith('().files') and not inserted:
                self.page.evaluate("""() => {
                    const input = document.createElement('input');
                    input.type = 'file'; input.id = 'unrelated';
                    document.body.prepend(input);
                }""")
                inserted.append(True)
            return result

        with patch.object(self.page, 'evaluate_handle', side_effect=hydrate_after_probe):
            self.upload()
        self.assertTrue(inserted, 'The DOM mutation must occur after input resolution')
        self.assertEqual(self.file_count("#selected"), 1)
        self.assertEqual(self.file_count("#unrelated"), 0)

    def test_input_diagnostics_report_structural_counts_without_page_content(self):
        self.show(outside='<input type="file" id="private-account-name" accept="image/*">')
        composer.diagnostic(self.page, self.temp.name, 'upload', 'input_failed')
        records = list((Path(self.temp.name) / 'composer-diagnostics').glob('*.json'))
        self.assertEqual(len(records), 1)
        content = records[0].read_text(encoding='utf-8')
        self.assertNotIn('private-account-name', content)
        state = json.loads(content)['composer']
        self.assertEqual(state['file_input_count'], 1)
        self.assertEqual(state['composer_file_input_count'], 0)

    def test_delayed_file_input_hydration_is_awaited(self):
        self.show(script='setTimeout(()=>{const input=document.createElement("input");'
                         'input.type="file";input.id="selected";input.style.display="none";'
                         'document.querySelector("#current-form").append(input);},200);')
        self.upload()
        self.assertEqual(self.file_count("#selected"), 1)

    def test_disabled_input_is_not_selected(self):
        self.show(siblings='<input type="file" id="selected" disabled style="display:none">')
        self.assert_rejected_without_upload("#selected")


if __name__ == "__main__":
    unittest.main()
