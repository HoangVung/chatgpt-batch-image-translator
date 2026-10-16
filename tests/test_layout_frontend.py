"""Isolated browser coverage for the per-book layout consistency controls.

Every bridge call uses the existing fake workflow bridge and temporary settings.
No worker, provider session, or production settings are accessed.
"""
import unittest
from pathlib import Path

import test_web_frontend as frontend_helpers
import test_workflow_frontend as workflow_helpers


class LayoutFrontendTests(unittest.TestCase):
    setUpClass = classmethod(frontend_helpers.WebFrontendTests.setUpClass.__func__)
    tearDownClass = classmethod(frontend_helpers.WebFrontendTests.tearDownClass.__func__)
    def setUp(self):
        workflow_helpers.WorkflowFrontendTests.setUp(self)
        self.page.set_default_timeout(8000)

    tearDown = workflow_helpers.WorkflowFrontendTests.tearDown

    def save_calls(self):
        return self.page.evaluate("calls.filter(call => call[0] === 'save_settings')")

    def save(self):
        count = len(self.save_calls())
        self.page.locator('#save').click()
        self.page.wait_for_function(
            "count => calls.filter(call => call[0] === 'save_settings').length > count",
            arg=count,
        )
        return self.save_calls()[-1]

    def install_picker(self):
        self.page.evaluate("""() => {
          window.pywebview.api.choose_layout_profile = id => {
            calls.push(['choose_layout_profile', id]);
            return new Promise(resolve => {
              window.finishLayoutPicker = (path, cancelled=false) =>
                resolve({ok:true,data:{path,cancelled}});
            });
          };
        }""")

    def test_default_off_and_backward_compatible_save(self):
        page = self.page
        self.assertTrue(page.locator('#layout-settings').is_visible())
        self.assertIn('Nhất quán trang sách', page.locator('#layout-settings').inner_text())
        self.assertFalse(page.locator('#layout-consistency').is_checked())
        self.assertFalse(page.locator('#layout-profile-options').is_visible())
        saved = self.save()
        self.assertEqual(saved[1], 'book-1')
        self.assertIs(saved[2]['layout_consistency_enabled'], False)
        self.assertEqual(saved[2]['layout_profile_path'], '')
        self.assertFalse(page.evaluate("calls.some(call => call[0] === 'start_batch')"))

    def test_enabled_default_profile_is_saved_before_start(self):
        page = self.page
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        self.assertTrue(page.locator('#layout-profile-options').is_visible())
        self.assertIn('1600', page.locator('#layout-profile').get_attribute('placeholder'))
        self.assertIn('2400', page.locator('#layout-profile').get_attribute('placeholder'))
        page.locator("button[data-mode='main']").click()
        page.wait_for_function("calls.some(call => call[0] === 'start_batch')")
        calls = page.evaluate('calls')
        self.assertEqual([call[0] for call in calls], ['save_settings', 'start_batch'])
        self.assertEqual(calls[0][1], 'book-1')
        self.assertIs(calls[0][2]['layout_consistency_enabled'], True)
        self.assertEqual(calls[0][2]['layout_profile_path'], '')
        self.assertEqual(calls[1][1], 'book-1')
        self.assertTrue(page.locator('#layout-consistency').is_disabled())

    def test_per_book_drafts_and_saved_payload_are_isolated(self):
        page = self.page
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        page.locator('#layout-profile').fill('D:/book-A/layout.json')
        page.locator('#tab-book-2').click()
        self.assertFalse(page.locator('#layout-consistency').is_checked())
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        page.locator('#layout-profile').fill('D:/book-B/layout.json')
        saved_b = self.save()
        self.assertEqual(saved_b[1], 'book-2')
        self.assertEqual(saved_b[2]['layout_profile_path'], 'D:/book-B/layout.json')
        page.locator('#tab-book-1').click()
        self.assertTrue(page.locator('#layout-consistency').is_checked())
        self.assertEqual(page.locator('#layout-profile').input_value(), 'D:/book-A/layout.json')
        saved_a = self.save()
        self.assertEqual(saved_a[1], 'book-1')
        self.assertIs(saved_a[2]['layout_consistency_enabled'], True)
        self.assertEqual(saved_a[2]['layout_profile_path'], 'D:/book-A/layout.json')
        page.locator('#tab-book-2').click()
        self.assertEqual(page.locator('#layout-profile').input_value(), 'D:/book-B/layout.json')
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        saved_off = self.save()
        self.assertIs(saved_off[2]['layout_consistency_enabled'], False)
        self.assertEqual(saved_off[2]['layout_profile_path'], 'D:/book-B/layout.json')

    def test_picker_result_belongs_to_origin_book_after_tab_switch(self):
        page = self.page
        self.install_picker()
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        page.locator('#layout-profile-browse').click()
        page.wait_for_function("typeof finishLayoutPicker === 'function'")
        page.locator('#tab-book-2').click()
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        page.locator('#layout-profile').fill('D:/book-B/keep.json')
        page.evaluate("finishLayoutPicker('D:/book-A/picked.json')")
        self.assertEqual(page.locator('#layout-profile').input_value(), 'D:/book-B/keep.json')
        page.locator('#tab-book-1').click()
        self.assertEqual(page.locator('#layout-profile').input_value(), 'D:/book-A/picked.json')
        self.assertTrue(page.locator('#layout-consistency').is_checked())
        self.assertEqual(page.evaluate("calls.filter(call => call[0] === 'choose_layout_profile')"),
                         [['choose_layout_profile', 'book-1']])

    def test_cancelled_picker_preserves_current_draft(self):
        page = self.page
        self.install_picker()
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        page.locator('#layout-profile').fill('D:/book-A/keep.json')
        page.locator('#layout-profile-browse').click()
        page.wait_for_function("typeof finishLayoutPicker === 'function'")
        page.evaluate("finishLayoutPicker('', true)")
        self.assertEqual(page.locator('#layout-profile').input_value(), 'D:/book-A/keep.json')
        self.assertTrue(page.locator('#layout-consistency').is_checked())
        self.assertEqual(self.save_calls(), [])

    def test_running_book_locks_layout_controls_but_idle_book_stays_editable(self):
        page = self.page
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        page.evaluate("emitWorkflow('book-1', 'process_started')")
        for selector in ('#layout-consistency', '#layout-profile', '#layout-profile-browse'):
            self.assertTrue(page.locator(selector).is_disabled(), selector)
        page.locator('#tab-book-2').click()
        self.assertFalse(page.locator('#layout-consistency').is_disabled())
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        self.assertFalse(page.locator('#layout-profile').is_disabled())
        page.locator('#tab-book-1').click()
        self.assertTrue(page.locator('#layout-consistency').is_disabled())
        page.evaluate("emitWorkflow('book-1', 'process_completed')")
        for selector in ('#layout-consistency', '#layout-profile', '#layout-profile-browse'):
            self.assertFalse(page.locator(selector).is_disabled(), selector)

    def test_gemini_hides_layout_and_chatgpt_restores_draft(self):
        page = self.page
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        page.locator('#layout-profile').fill('D:/book-A/layout.json')
        page.locator('#service').select_option('gemini')
        self.assertFalse(page.locator('#layout-settings').is_visible())
        page.locator('#service').select_option('chatgpt')
        self.assertTrue(page.locator('#layout-settings').is_visible())
        self.assertTrue(page.locator('#layout-consistency').is_checked())
        self.assertEqual(page.locator('#layout-profile').input_value(), 'D:/book-A/layout.json')

    def test_layout_controls_fit_light_dark_and_system_themes(self):
        page = self.page
        page.locator('label').filter(has=page.locator('#layout-consistency')).click()
        page.locator('#layout-profile').fill('D:/books/a-very-long-book-name/layout-profiles/approved-layout-for-this-book.json')
        target = frontend_helpers.PROJECT_ROOT / 'output' / 'full-reflow-app-ui-verification'
        target.mkdir(parents=True, exist_ok=True)
        for theme, scheme, name in (
            ('light', 'light', 'light'), ('dark', 'dark', 'dark'),
            ('system', 'light', 'system-light'), ('system', 'dark', 'system-dark'),
        ):
            with self.subTest(theme=name):
                page.emulate_media(color_scheme=scheme)
                page.locator('#theme').select_option(theme)
                page.wait_for_function(
                    "theme => theme === 'system' ? !document.documentElement.hasAttribute('data-theme') : document.documentElement.dataset.theme === theme",
                    arg=theme,
                )
                for width, height in ((1180, 820), (980, 760)):
                    with self.subTest(viewport=(width, height)):
                        page.set_viewport_size({'width': width, 'height': height})
                        page.wait_for_timeout(200)
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth'))
                        card = page.locator('#configuration-card').bounding_box()
                        for selector in ('#layout-settings', '#layout-profile', '#layout-profile-browse'):
                            self.assertTrue(page.locator(selector).is_visible(), selector)
                            box = page.locator(selector).bounding_box()
                            self.assertGreaterEqual(box['x'], card['x'], selector)
                            self.assertLessEqual(box['x'] + box['width'], card['x'] + card['width'] + 1, selector)
                            self.assertLessEqual(box['x'] + box['width'], width + 1, selector)
                        suffix = '' if width == 1180 else '-980'
                        page.screenshot(path=target / f'layout-{name}{suffix}.png', full_page=True)

    def test_full_reflow_stays_on_origin_tab_and_never_starts_batch(self):
        page = self.page
        page.evaluate("""() => {
          window.pywebview.api.full_reflow_saved = (folder,id) => {
            calls.push(['full_reflow_saved',folder,id]);
            return new Promise(resolve => window.finishReflow = () => resolve({ok:true,data:{cancelled:false,pages:2,succeeded:1,failed:0,output:'D:/preview'}}));
          };
        }""")
        page.locator('#output-folder').fill('D:/book-A')
        page.locator('#full-reflow-saved').click()
        page.wait_for_function("calls.some(c => c[0] === 'full_reflow_saved')")
        self.assertEqual(page.evaluate("calls.find(c => c[0] === 'full_reflow_saved').slice(1)"), ['D:/book-A','book-1'])
        self.assertTrue(page.locator('#full-reflow-saved').is_disabled())
        page.locator('#tab-book-2').click()
        page.evaluate('finishReflow()')
        page.wait_for_timeout(100)
        self.assertEqual(page.locator('#full-reflow-status').inner_text(), '')
        page.locator('#tab-book-1').click()
        self.assertIn('2 trang', page.locator('#full-reflow-status').inner_text())
        self.assertFalse(page.evaluate("calls.some(c => c[0] === 'start_batch' || c[0] === 'save_settings')"))
        self.assertEqual(self.errors, [])

    def test_full_reflow_error_restores_controls(self):
        page = self.page
        page.evaluate("window.pywebview.api.full_reflow_saved = async () => ({ok:false,error:'Missing saved math evidence'})")
        page.locator('#full-reflow-saved').click()
        page.wait_for_function("document.querySelector('#notice').textContent.includes('Missing saved math evidence')")
        self.assertFalse(page.locator('#full-reflow-saved').is_disabled())
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
