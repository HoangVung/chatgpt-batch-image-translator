import json
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from desktop.web_text import WEB_TEXT


class WebFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise unittest.SkipTest("Playwright is required for web frontend smoke tests")
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except PlaywrightError as bundled_error:
            try:
                cls.browser = cls.playwright.chromium.launch(channel="msedge", headless=True)
            except PlaywrightError as edge_error:
                cls.playwright.stop()
                raise unittest.SkipTest(
                    f"Playwright Chromium and Microsoft Edge are unavailable: {bundled_error}; {edge_error}"
                ) from edge_error

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_initial_render_events_and_main_command_use_fake_bridge(self):
        page = self.browser.new_page()
        initial = {
            "settings": {
                "image_folder": "D:/source/a-very-long-volume-name/with/nested/folders/that/must/not/stretch/the-window",
                "download_folder": "D:/output",
                "profile_dir": "D:/profile",
                "gemini_profile_dir": "D:/gemini",
                "chatgpt_accounts": [
                    {"id": "default", "name": "ChatGPT 1", "profile_dir": "D:/profile"},
                    {"id": "business", "name": "Business", "profile_dir": "D:/business"},
                ],
                "active_chatgpt_account_id": "business",
                "auto_account_fallback_enabled": True,
                "batch_size": "10",
                "start_from": "",
                "auto_next_enabled": True,
                "auto_next_delay_minutes": "2",
                "theme": "system",
                "language": "vi",
                "service": "chatgpt",
            },
            "controller": {
                "running": False,
                "progress_done": 0,
                "progress_total": 0,
                "manual_action_required": False,
                "log_history": "initial log\n",
                "status": {"key": "ready", "params": {}},
                "sequence": 0,
            },
            "localization": WEB_TEXT,
            "capabilities": {"webview_backend": "fake-webview2"},
        }
        bootstrap = """
          window.bridgeCalls = [];
          const initial = JSON.parse(%s);
          const ok = (data={}) => Promise.resolve({ok:true, data});
          window.pywebview = {api: {
            get_initial_state: () => ok(initial),
            save_settings: (payload) => { bridgeCalls.push(['save_settings', payload]); Object.assign(initial.settings, payload); return ok({settings: initial.settings}); },
            start_batch: (mode) => { bridgeCalls.push(['start_batch', mode]); return ok({state: initial.controller}); },
            choose_folder: (kind) => ok({kind, path:'D:/picked', cancelled:false}),
            stop_process: () => ok(), continue_manual_intervention: () => ok(),
            cancel_auto_next: () => ok(), run_auto_next_now: () => ok(),
            open_output_folder: () => { bridgeCalls.push(['open_output_folder']); return ok(); },
            copy_log: () => ok(), export_log: () => ok(), clear_log: () => ok(),
            select_account: (id) => { bridgeCalls.push(['select_account', id]); return ok({accounts:initial.settings.chatgpt_accounts,active_id:id}); },
            add_account: (name) => { bridgeCalls.push(['add_account', name]); return ok({accounts:initial.settings.chatgpt_accounts,active_id:'business'}); },
            rename_account: (id, name) => { bridgeCalls.push(['rename_account', id, name]); return ok({accounts:initial.settings.chatgpt_accounts,active_id:id}); },
            remove_account: (id) => { bridgeCalls.push(['remove_account', id]); return ok({accounts:initial.settings.chatgpt_accounts.filter(a => a.id !== id),active_id:'default'}); },
            login_account: () => ok()
          }};
        """ % json.dumps(json.dumps(initial, ensure_ascii=False))
        page.add_init_script(bootstrap)
        page.goto((PROJECT_ROOT / "ui" / "index.html").as_uri())
        page.wait_for_function("document.querySelector('#status').textContent === 'Sẵn sàng'")

        self.assertEqual(page.locator("#backend").text_content(), "fake-webview2")
        self.assertEqual(page.locator("#log").text_content(), "initial log\n")
        self.assertEqual(page.locator("#account-select option").count(), 2)
        self.assertEqual(page.locator("#account-select").input_value(), "business")
        self.assertEqual(page.locator("#account-context").text_content(), "Business")
        self.assertEqual(page.locator("#source-folder").get_attribute("title"), initial["settings"]["image_folder"])

        page.locator("#theme").select_option("dark")
        page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
        page.wait_for_function("getComputedStyle(document.querySelector('#source-folder')).backgroundColor.includes('9, 14, 23')")
        self.assertEqual(page.locator("html").get_attribute("data-theme"), "dark")
        dark_field = page.locator("#source-folder").evaluate("node => getComputedStyle(node).backgroundColor")
        self.assertIn("9, 14, 23", dark_field)
        dark_log_card = page.locator(".log-card").evaluate("node => getComputedStyle(node).backgroundColor")
        dark_log_surface = page.locator("#log").evaluate("node => getComputedStyle(node).backgroundColor")
        self.assertIn("27, 36, 51", dark_log_card)
        self.assertIn("17, 25, 38", dark_log_surface)
        screenshot_dir = os.environ.get("PHASE4_SCREENSHOT_DIR")
        if screenshot_dir:
            target = Path(screenshot_dir)
            target.mkdir(parents=True, exist_ok=True)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(path=target / "phase4a-dark.png", full_page=True)

        page.locator("#theme").select_option("light")
        page.wait_for_function("document.documentElement.dataset.theme === 'light'")
        page.wait_for_timeout(220)
        self.assertEqual(page.locator("html").get_attribute("data-theme"), "light")
        light_log_card = page.locator(".log-card").evaluate("node => getComputedStyle(node).backgroundColor")
        light_log_surface = page.locator("#log").evaluate("node => getComputedStyle(node).backgroundColor")
        self.assertIn("244, 248, 253", light_log_card)
        self.assertIn("255, 255, 255", light_log_surface)
        page.evaluate("""
          window.batchTranslatorReceive({sequence:1,type:'progress_changed',payload:{done:4,total:10}});
          window.batchTranslatorReceive({sequence:2,type:'log_appended',payload:{text:'next log\\n'}});
          window.batchTranslatorReceive({sequence:3,type:'manual_action_required',payload:{}});
          window.batchTranslatorReceive({sequence:4,type:'auto_next_scheduled',payload:{seconds:5}});
          window.batchTranslatorReceive({sequence:5,type:'auto_next_tick',payload:{remaining:5}});
        """)
        self.assertIn("4 / 10 (40%)", page.locator("#progress-text").text_content())
        self.assertIn("next log", page.locator("#log").text_content())
        self.assertTrue(page.locator("#manual-banner").is_visible())
        self.assertTrue(page.locator("#auto-panel").is_visible())
        self.assertIn("00:05", page.locator("#countdown").text_content())

        page.evaluate("window.bridgeCalls = []")
        page.evaluate("""
          const button = document.querySelector("button[data-mode='main']");
          button.click();
          button.click();
        """)
        page.wait_for_function("window.bridgeCalls.some(call => call[0] === 'start_batch')")
        calls = page.evaluate("window.bridgeCalls")
        self.assertEqual([call[0] for call in calls], ["save_settings", "start_batch"])

        page.evaluate("window.bridgeCalls = []")
        for mode in ("main", "retry", "force"):
            page.locator(f"button[data-mode='{mode}']").click()
            page.wait_for_function(
                "mode => window.bridgeCalls.some(call => call[0] === 'start_batch' && call[1] === mode)",
                arg=mode,
            )
        calls = page.evaluate("window.bridgeCalls")
        self.assertEqual([call[0] for call in calls[-2:]], ["save_settings", "start_batch"])

        page.evaluate("window.bridgeCalls = []")
        page.locator("#open-output").click()
        page.wait_for_function("window.bridgeCalls.some(call => call[0] === 'open_output_folder')")
        self.assertEqual(page.evaluate("window.bridgeCalls"), [["open_output_folder"]])

        page.evaluate("window.batchTranslatorReceive({sequence:6,type:'process_started',payload:{mode:'main'}})")
        self.assertTrue(page.locator("body").evaluate("node => node.classList.contains('is-running')"))
        self.assertTrue(page.locator("button[data-mode='main']").is_disabled())
        self.assertTrue(page.locator("#account-remove").is_disabled())
        self.assertFalse(page.locator("#stop").is_disabled())

        page.evaluate("window.batchTranslatorReceive({sequence:8,type:'status_changed',payload:{key:'status_running',params:{}}})")
        self.assertTrue(page.locator("#notice").is_visible())
        self.assertIn("7", page.locator("#notice").text_content())
        page.evaluate("window.batchTranslatorReceive({sequence:9,type:'bridge_error',payload:{error:'visual smoke error'}})")
        self.assertIn("visual smoke error", page.locator("#notice").text_content())

        page.evaluate("window.batchTranslatorReceive({sequence:10,type:'process_completed',payload:{exit_code:0}})")
        page.evaluate("window.batchTranslatorReceive({sequence:11,type:'status_changed',payload:{key:'ready',params:{}}})")
        self.assertFalse(page.locator("button[data-mode='main']").is_disabled())
        self.assertFalse(page.locator("body").evaluate("node => node.classList.contains('is-running')"))

        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#account-remove").click()
        page.wait_for_function("window.bridgeCalls.some(call => call[0] === 'remove_account' && call[1] === 'business')")
        self.assertEqual(page.locator("#account-select option").count(), 1)
        self.assertIn("danger", page.locator("#account-remove").get_attribute("class"))

        for width, height in ((1440, 1000), (720, 900)):
            page.set_viewport_size({"width": width, "height": height})
            self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"))

        if screenshot_dir:
            page.set_viewport_size({"width": 1180, "height": 920})
            page.screenshot(path=Path(screenshot_dir) / "phase4a-light.png", full_page=True)
        page.close()

    def test_realtime_log_arriving_during_initial_snapshot_is_not_overwritten(self):
        page = self.browser.new_page()
        initial = {
            "settings": {
                "image_folder": "D:/source", "download_folder": "D:/output", "profile_dir": "D:/profile",
                "gemini_profile_dir": "D:/gemini", "chatgpt_accounts": [
                    {"id": "default", "name": "ChatGPT 1", "profile_dir": "D:/profile"},
                ],
                "active_chatgpt_account_id": "default", "auto_account_fallback_enabled": True,
                "batch_size": "1", "start_from": "", "auto_next_enabled": False,
                "auto_next_delay_minutes": "2", "theme": "system", "language": "vi", "service": "chatgpt",
            },
            "controller": {
                "running": False, "progress_done": 0, "progress_total": 0,
                "manual_action_required": False, "log_history": "snapshot log\n",
                "status": {"key": "ready", "params": {}}, "sequence": 0,
            },
            "localization": WEB_TEXT,
            "capabilities": {"webview_backend": "fake-webview2"},
        }
        bootstrap = """
          const initial = JSON.parse(%s);
          window.initialStatePromise = new Promise(resolve => { window.resolveInitialState = resolve; });
          window.pywebview = {api: {
            get_initial_state: () => window.initialStatePromise,
            save_settings: () => Promise.resolve({ok:true,data:{settings:initial.settings}})
          }};
        """ % json.dumps(json.dumps(initial, ensure_ascii=False))
        page.add_init_script(bootstrap)
        page.goto((PROJECT_ROOT / "ui" / "index.html").as_uri())
        page.evaluate("window.batchTranslatorReceive({sequence:1,type:'log_appended',payload:{text:'realtime log\\n'}})")
        page.evaluate(
            "raw => window.resolveInitialState({ok:true,data:JSON.parse(raw)})",
            json.dumps(initial, ensure_ascii=False),
        )
        page.wait_for_function("document.querySelector('#log').textContent.includes('realtime log')")
        self.assertEqual(page.locator("#log").text_content(), "snapshot log\nrealtime log\n")
        page.close()


if __name__ == "__main__":
    unittest.main()
