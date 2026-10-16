"""Regression cases for composer menus and clicks with uncertain completion."""
import base64
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from playwright.sync_api import ElementHandle, TimeoutError as PlaywrightTimeoutError, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import books34_composer as composer


class ComposerUploadRecoveryTests(unittest.TestCase):
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

    def show(self, outside="", script=""):
        self.page.set_content(
            '<main><form id="current-form"><div id="composer-background">'
            '<div id="prompt-textarea" contenteditable="true" style="height:40px;width:400px"></div>'
            '<button type="button" id="composer-plus-btn" aria-label="Add files and more" '
            'aria-haspopup="menu" aria-controls="attachment-menu" aria-expanded="false">+</button>'
            '<button type="submit" data-testid="send-button">Send</button>'
            '</div></form></main>' + outside
            + '<script>window.sent=0;window.attachClicks=0;window.uploadClicks=0;'
            + 'document.querySelector("form").onsubmit=e=>{e.preventDefault();window.sent++;};'
            + script + '</script>'
        )

    def upload(self, timeout=5):
        composer.upload(self.page, self.image, timeout=timeout)
        self.assertEqual(self.page.evaluate("window.sent"), 0)

    def assert_uploaded_once(self):
        self.assertEqual(self.page.locator("#selected").evaluate("el => el.files.length"), 1)
        self.assertEqual(self.page.evaluate("window.attachClicks"), 1)
        self.assertEqual(self.page.evaluate("window.sent"), 0)

    def timeout_after_click(self, target_id):
        original = ElementHandle.click

        def click_then_timeout(element, *args, **kwargs):
            selected = element.get_attribute("id") == target_id
            result = original(element, *args, **kwargs)
            if selected:
                raise PlaywrightTimeoutError("Injected timeout after the browser received the click")
            return result

        return patch.object(ElementHandle, "click", click_then_timeout)

    def test_chooser_received_before_click_timeout_is_uploaded_once(self):
        self.show(script='document.querySelector("#composer-plus-btn").onclick=()=>{'
                         'window.attachClicks++;const input=document.createElement("input");'
                         'input.type="file";input.id="selected";input.style.display="none";'
                         'document.body.append(input);input.click();};')
        with self.timeout_after_click("composer-plus-btn"):
            self.upload()
        self.assert_uploaded_once()

    def test_mouse_timeout_without_effect_can_use_keyboard_attachment(self):
        self.show(script='document.querySelector("#composer-plus-btn").onclick=()=>{'
                         'window.attachClicks++;const input=document.createElement("input");'
                         'input.type="file";input.id="selected";input.style.display="none";'
                         'document.body.append(input);input.click();};')
        with patch.object(ElementHandle, "click", side_effect=PlaywrightTimeoutError("Mouse action did not run")):
            self.upload()
        self.assert_uploaded_once()

    def menu(self, label="Add photos &amp; files", menu_script="", menu_contents="", open_script=""):
        self.show(
            outside='<input type="file" id="capture-unrelated" accept="image/*" capture="environment" '
                    'style="display:none"><div role="menu" id="attachment-menu" style="display:none">'
                    '<button type="button" role="menuitem" id="upload-local">' + label + '</button>'
                    + menu_contents + '</div>',
            script='document.querySelector("#composer-plus-btn").onpointerdown=e=>{'
                   'if(e.button!==0)return;window.attachClicks++;'
                   'e.currentTarget.setAttribute("aria-expanded","true");'
                   'document.querySelector("#attachment-menu").style.display="block";'
                   + open_script + '};'
                   + menu_script,
        )

    def menu_chooser_script(self):
        return ('document.querySelector("#upload-local").onclick=()=>{window.uploadClicks++;'
                'const input=document.createElement("input");input.type="file";input.id="selected";'
                'input.style.display="none";document.body.append(input);input.click();};')

    def test_pointerdown_opened_menu_survives_trigger_click_timeout(self):
        self.menu(menu_script=self.menu_chooser_script())
        with self.timeout_after_click("composer-plus-btn"):
            self.upload()
        self.assert_uploaded_once()
        self.assertEqual(self.page.evaluate("window.uploadClicks"), 1)
        self.assertEqual(self.page.locator("#capture-unrelated").evaluate("el => el.files.length"), 0)

    def test_menu_chooser_received_before_menu_click_timeout_is_uploaded_once(self):
        self.menu(menu_script=self.menu_chooser_script())
        with self.timeout_after_click("upload-local"):
            self.upload()
        self.assert_uploaded_once()
        self.assertEqual(self.page.evaluate("window.uploadClicks"), 1)

    def test_upload_item_ignores_aria_hidden_keyboard_shortcut(self):
        self.menu(label='Add photos &amp; files<span aria-hidden="true">Ctrl+U</span>',
                  menu_script=self.menu_chooser_script())
        self.upload()
        self.assert_uploaded_once()
        self.assertEqual(self.page.evaluate("window.uploadClicks"), 1)

    def test_new_menu_owned_input_is_used_without_unrelated_capture_input(self):
        self.menu(
            menu_script='document.querySelector("#composer-plus-btn").removeAttribute("aria-controls");',
            open_script='const input=document.createElement("input");input.type="file";'
                        'input.id="selected";input.accept="image/*,.pdf";input.multiple=true;'
                        'input.style.display="none";document.querySelector("#attachment-menu").append(input);',
        )
        self.upload()
        self.assert_uploaded_once()
        self.assertEqual(self.page.locator("#capture-unrelated").evaluate("el => el.files.length"), 0)

    def test_new_menu_skips_camera_and_directory_inputs(self):
        self.menu(
            menu_script='document.querySelector("#composer-plus-btn").removeAttribute("aria-controls");',
            open_script='document.querySelector("#attachment-menu").insertAdjacentHTML("beforeend",'
                        '\'<input type="file" id="capture-menu" accept="image/*" capture="environment" style="display:none">'
                        '<input type="file" id="directory-menu" webkitdirectory style="display:none">'
                        '<input type="file" id="selected" accept="image/*,.pdf" multiple style="display:none">\');',
        )
        self.upload()
        self.assert_uploaded_once()
        for selector in ("#capture-unrelated", "#capture-menu", "#directory-menu"):
            self.assertEqual(self.page.locator(selector).evaluate("el => el.files.length"), 0)

    def test_unmarked_page_shell_does_not_own_sibling_settings_input(self):
        self.show()
        self.page.evaluate("""() => {
            document.querySelector('#composer-plus-btn').remove();
            const main = document.querySelector('main');
            const shell = document.createElement('div');
            shell.id = 'page-shell';
            main.append(shell);
            shell.append(document.querySelector('form'));
            shell.insertAdjacentHTML('beforeend', '<section id="upload-settings">'
                + '<input type="file" id="unrelated" accept="image/*" style="display:none"></section>');
        }""")
        self.assertEqual(composer.inspect(self.page)["composer_file_input_count"], 0)
        with self.assertRaises(RuntimeError):
            self.upload(timeout=0.5)
        self.assertEqual(self.page.locator("#unrelated").evaluate("el => el.files.length"), 0)
        self.assertEqual(self.page.evaluate("window.sent"), 0)

    def test_marked_composer_wrapper_owns_sibling_file_input(self):
        self.show()
        self.page.evaluate("""() => {
            const main = document.querySelector('main');
            const wrapper = document.createElement('div');
            wrapper.setAttribute('data-testid', 'composer');
            main.append(wrapper);
            wrapper.append(document.querySelector('form'));
            wrapper.insertAdjacentHTML('beforeend', '<input type="file" id="selected" '
                + 'accept="image/*" style="display:none">');
        }""")
        self.assertEqual(composer.inspect(self.page)["composer_file_input_count"], 1)
        self.upload()
        self.assertEqual(self.page.locator("#selected").evaluate("el => el.files.length"), 1)
        self.assertEqual(self.page.evaluate("window.attachClicks"), 0)


if __name__ == "__main__":
    unittest.main()
