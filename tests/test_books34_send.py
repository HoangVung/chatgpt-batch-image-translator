"""Books 3/4 send ownership, using offline DOM fixtures in real Chromium."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from playwright.sync_api import ElementHandle, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import books34_composer as composer


class ComposerSendTests(unittest.TestCase):
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
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.context.route("**/*", lambda route: route.abort())
        self.page = self.context.new_page()

    def show(self, html):
        self.page.set_content(html + '''<script>
            window.clicked = [];
            document.addEventListener('click', event => {
                const button = event.target.closest('button');
                if (button) window.clicked.push(button.id);
            });
            document.addEventListener('submit', event => event.preventDefault());
        </script>''')

    @staticmethod
    def editor():
        return ('<div id="prompt-textarea" contenteditable="true" '
                'style="height:40px;width:400px">Translate</div>')

    @staticmethod
    def button(name="selected", attributes=""):
        return ('<button type="button" data-testid="send-button" id="' + name
                + '" ' + attributes + '>Send</button>')

    def assert_sent(self):
        self.assertTrue(composer.send_ready(self.page))
        self.assertEqual(self.page.evaluate("window.clicked"), [])
        self.assertTrue(composer.click_send(self.page))
        self.assertEqual(self.page.evaluate("window.clicked"), ["selected"])

    def assert_not_sent(self):
        self.assertFalse(composer.send_ready(self.page))
        self.assertFalse(composer.click_send(self.page))
        self.assertEqual(self.page.evaluate("window.clicked"), [])

    def test_inline_button(self):
        self.show('<main><form><div id="composer-background">'
                  + self.editor() + self.button() + '</div></form></main>')
        self.assert_sent()

    def test_button_beside_inner_composer_in_same_form(self):
        self.show('<main><form><div id="composer-background">'
                  + self.editor() + '</div>' + self.button() + '</form></main>')
        self.assert_sent()

    def test_button_beside_form_in_explicit_composer(self):
        for marker in ('id="composer-background"', 'data-testid="composer"',
                       'data-testid="composer-container"',
                       'data-type="unified-composer"',
                       'class="ComposerLayoutRoot-shell"'):
            with self.subTest(marker=marker):
                self.show('<main><section ' + marker + '><form>'
                          + self.editor() + '</form>' + self.button()
                          + '</section></main>')
                self.assert_sent()

    def test_unrelated_button_in_ordinary_page_wrapper(self):
        self.show('<main><section><form><div id="composer-background">'
                  + self.editor() + '</div></form>' + self.button("unrelated")
                  + '</section></main>')
        self.assert_not_sent()

    def test_unrelated_button_outside_composer_does_not_steal_send(self):
        self.show(self.button("unrelated") + '<main><form><div id="composer-background">'
                  + self.editor() + self.button() + '</div></form></main>')
        self.assert_sent()

    def test_navigation_and_history_buttons_are_never_used(self):
        for tag, attributes in (
            ('nav', ''), ('aside', ''), ('div', 'role="navigation"'),
            ('div', 'data-testid="conversation-turn-2"'),
            ('div', 'data-message-author-role="assistant"'),
            ('div', 'data-turn="user"'),
            ('div', 'data-content-search-turn-key="old-turn"'),
            ('div', 'data-content-search-unit-key="old-unit"'),
            ('user-query', ''), ('model-response', ''),
        ):
            with self.subTest(tag=tag, attributes=attributes):
                self.show('<main><form><' + tag + ' ' + attributes + '>'
                          + self.button("unrelated") + '</' + tag + '>'
                          + '<div id="composer-background">' + self.editor()
                          + self.button() + '</div></form></main>')
                self.assert_sent()

    def test_nested_dialog_button_is_rejected(self):
        self.show('<main><form><div id="composer-background">' + self.editor()
                  + '<div role="dialog">' + self.button("unrelated") + '</div>'
                  + self.button() + '</div></form></main>')
        self.assert_sent()

    def test_button_in_editor_dialog_is_allowed(self):
        self.show('<div role="dialog"><form><div id="composer-background">'
                  + self.editor() + self.button() + '</div></form></div>')
        self.assert_sent()

    def test_button_associated_with_different_form_is_rejected(self):
        self.show('<form id="unrelated-form"></form><main><form id="current-form">'
                  + '<div id="composer-background">' + self.editor()
                  + self.button("unrelated", 'form="unrelated-form"')
                  + self.button() + '</div></form></main>')
        self.assert_sent()

    def test_disabled_or_hidden_button_is_rejected(self):
        for attributes in ('disabled', 'aria-disabled="true"', 'hidden',
                           'style="display:none"', 'style="visibility:hidden"'):
            with self.subTest(attributes=attributes):
                self.show('<form><div id="composer-background">' + self.editor()
                          + self.button("unrelated", attributes)
                          + self.button() + '</div></form>')
                self.assert_sent()

    def test_inert_or_aria_disabled_ancestor_is_rejected(self):
        for attributes in ('inert', 'aria-disabled="true"'):
            with self.subTest(attributes=attributes):
                self.show('<form><div id="composer-background">' + self.editor()
                          + '<div ' + attributes + '>' + self.button("unrelated")
                          + '</div>' + self.button() + '</div></form>')
                self.assert_sent()

    def test_disabled_button_without_alternative_does_not_send(self):
        self.show('<form><div id="composer-background">' + self.editor()
                  + self.button(attributes="disabled") + '</div></form>')
        self.assert_not_sent()

    def test_missing_editor_does_not_send(self):
        self.show('<form><div id="composer-background">'
                  + self.button() + '</div></form>')
        self.assert_not_sent()

    def test_disabled_editor_does_not_send(self):
        self.show('<form><div id="composer-background"><div aria-disabled="true">'
                  + self.editor() + '</div>' + self.button() + '</div></form>')
        self.assert_not_sent()


    def test_send_ready_does_not_click_or_change_page(self):
        self.show('<form><div id="composer-background">' + self.editor()
                  + self.button() + '</div></form>')
        before = self.page.content()
        with patch.object(ElementHandle, 'click', side_effect=AssertionError('readiness clicked')):
            self.assertTrue(composer.send_ready(self.page))
        self.assertEqual(self.page.evaluate("window.clicked"), [])
        self.assertEqual(self.page.content(), before)

    def test_send_ready_is_false_for_hidden_or_disabled_only_control(self):
        for attributes in ('disabled', 'aria-disabled="true"', 'hidden',
                           'style="display:none"', 'style="visibility:hidden"'):
            with self.subTest(attributes=attributes):
                self.show('<form><div id="composer-background">' + self.editor()
                          + self.button(attributes=attributes) + '</div></form>')
                self.assertFalse(composer.send_ready(self.page))
                self.assertEqual(self.page.evaluate("window.clicked"), [])

    def read_send_diagnostic(self, reason):
        with tempfile.TemporaryDirectory() as directory:
            with patch('builtins.print') as output:
                composer.diagnostic(self.page, directory, 'send', reason)
            paths = list((Path(directory) / 'composer-diagnostics').glob('*.json'))
            self.assertEqual(len(paths), 1)
            raw = paths[0].read_text(encoding='utf-8')
        return json.loads(raw), raw, str(output.call_args_list)

    def test_send_diagnostics_are_structural_bounded_and_stage_specific(self):
        secret = 'private-editor-secret-9281'
        unrelated = ''.join(self.button('private-button-' + str(index)) for index in range(20))
        self.show(unrelated + '<form><div id="composer-background">'
                  + self.editor().replace('Translate', secret)
                  + self.button('hidden', 'hidden')
                  + self.button('disabled', 'disabled')
                  + self.button() + '<a href="https://private.example/secret">private-link</a>'
                  + '</div></form>')
        payload, raw, printed = self.read_send_diagnostic('not_ready_before_typing')
        self.assertEqual(payload['phase'], 'send')
        self.assertEqual(payload['reason'], 'not_ready_before_typing')
        state = payload['send_controls']
        self.assertTrue(state['editor_found'])
        self.assertTrue(state['composer_found'])
        self.assertTrue(state['upload_root_found'])
        self.assertEqual(state['matched_count'], 23)
        self.assertEqual(state['in_root_count'], 3)
        self.assertEqual(state['owned_count'], 3)
        self.assertEqual(state['eligible_count'], 2)
        self.assertEqual(state['visible_count'], 22)
        self.assertEqual(state['enabled_count'], 22)
        self.assertEqual(state['ready_count'], 1)
        self.assertEqual(len(state['controls']), 12)
        for control in state['controls']:
            self.assertTrue(all(isinstance(value, bool) for value in control.values()))
        for private_value in (secret, 'private-button-', 'private.example', 'private-link', '<form'):
            self.assertNotIn(private_value, raw)
            self.assertNotIn(private_value, printed)
        self.assertEqual(self.page.evaluate("window.clicked"), [])

    def test_send_diagnostics_distinguish_no_matching_control(self):
        self.show('<form><div id="composer-background">' + self.editor() + '</div></form>')
        payload, _, _ = self.read_send_diagnostic('not_ready_after_typing')
        self.assertEqual(payload['reason'], 'not_ready_after_typing')
        state = payload['send_controls']
        self.assertTrue(state['editor_found'])
        self.assertTrue(state['composer_found'])
        self.assertEqual(state['matched_count'], 0)
        self.assertEqual(state['ready_count'], 0)

    def test_send_diagnostics_distinguish_disabled_editor(self):
        self.show('<form><div id="composer-background"><div aria-disabled="true">'
                  + self.editor() + '</div>' + self.button() + '</div></form>')
        payload, _, _ = self.read_send_diagnostic('not_ready_before_typing')
        state = payload['send_controls']
        self.assertFalse(state['editor_found'])
        self.assertTrue(state['composer_found'])
        self.assertEqual(state['matched_count'], 1)
        self.assertEqual(state['owned_count'], 0)
        self.assertEqual(state['ready_count'], 0)

    def test_later_inserted_unrelated_button_does_not_change_candidate(self):
        self.show('<form><div id="composer-background">'
                  + self.editor() + self.button() + '</div></form>')
        original = self.page.evaluate_handle

        def insert_after_probe(*args, **kwargs):
            result = original(*args, **kwargs)
            self.page.evaluate('''() => {
                const button = document.createElement('button');
                button.id = 'unrelated'; button.dataset.testid = 'send-button';
                button.textContent = 'Send'; document.body.prepend(button);
            }''')
            return result

        with patch.object(self.page, 'evaluate_handle', side_effect=insert_after_probe):
            self.assert_sent()


if __name__ == "__main__":
    unittest.main()
