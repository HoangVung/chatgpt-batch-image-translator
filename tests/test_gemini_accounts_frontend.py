"""Real web UI calls into the account backend with fake worker processes."""
import tempfile
from pathlib import Path
import unittest

from desktop.web_api import WebApi
from desktop.workflow_sessions import GLOBAL_METHODS, SessionManager
from desktop_controller import DesktopController
from test_web_api import FakeScheduler, Factory, FakeThread
import test_web_frontend as frontend_helpers

PROJECT_ROOT = frontend_helpers.PROJECT_ROOT


class GeminiAccountsFrontendTests(unittest.TestCase):
    setUpClass = classmethod(frontend_helpers.WebFrontendTests.setUpClass.__func__)
    tearDownClass = classmethod(frontend_helpers.WebFrontendTests.tearDownClass.__func__)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.factories = {}

        def factory(**kwargs):
            scheduler, processes = FakeScheduler(), Factory()
            self.factories[kwargs["session_id"]] = processes
            controller = DesktopController(scheduler, popen_factory=processes, thread_factory=FakeThread,
                                           process_tree_terminator=lambda process: setattr(process, "return_code", 0))
            return WebApi(scheduler=scheduler, controller=controller, **kwargs)

        self.manager = SessionManager(app_dir=PROJECT_ROOT, data_dir=Path(self.temp.name), api_factory=factory)
        self.page = self.browser.new_page(viewport={"width": 1180, "height": 820})
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

        def bridge(method, args):
            session = args.pop() if args and args[-1] in self.manager.sessions and method not in GLOBAL_METHODS else None
            return self.manager._invoke(method, args, session)

        self.page.expose_function("accountTestBridge", bridge)
        self.page.add_init_script("""
            window.pywebview = {api: new Proxy({}, {
                get: (_, method) => (...args) => window.accountTestBridge(method, args)
            })};
        """)
        self.page.goto((PROJECT_ROOT / "ui/index.html").as_uri())
        self.page.wait_for_selector("#tab-book-2")

    def tearDown(self):
        self.page.close()
        self.manager._shutdown()
        self.temp.cleanup()
        self.assertEqual(self.errors, [])

    def add(self, name):
        self.page.locator("#account-name").fill(name)
        self.page.locator("#account-add").click()
        self.page.wait_for_function("name => document.querySelector('#account-name').value === name && !document.querySelector('#account-add').disabled", arg=name)

    def test_switch_to_gemini_then_add_rename_select_and_signin_without_manual_save(self):
        page = self.page
        chatgpt = self.manager.sessions["book-1"].settings["chatgpt_accounts"].copy()
        page.locator("#service").select_option("gemini")
        self.assertTrue(page.locator("#accounts-card").is_visible())
        self.assertEqual(page.locator("#account-label").text_content(), "Tài khoản Gemini")
        self.assertEqual(page.locator("#account-name").input_value(), "Gemini 1")
        self.add("Google công việc")
        self.assertEqual(page.locator("#account-count").text_content(), "2")
        api = self.manager.sessions["book-1"]
        account_id = api.settings["active_gemini_account_id"]
        profile = api.settings["profile_dir"]
        self.assertEqual(api.settings["service"], "gemini")
        self.assertEqual(api.settings["chatgpt_accounts"], chatgpt)
        self.assertEqual(page.locator("#profile-folder").input_value(), profile)
        page.locator("#account-name").fill("Google cá nhân")
        page.locator("#account-rename").click()
        page.wait_for_function("document.querySelector('#account-select').selectedOptions[0].textContent === 'Google cá nhân'")
        self.assertIn("Google cá nhân", page.locator("#tab-book-1").text_content())
        page.locator("#account-login").click()
        page.wait_for_function("document.querySelector('#account-login').disabled && document.body.classList.contains('is-running')")
        env = self.factories["book-1"].calls[-1][1]["env"]
        self.assertEqual(env["SERVICE"], "gemini")
        self.assertEqual(env["PROFILE_DIR"], profile)
        self.assertEqual(api.settings["active_gemini_account_id"], account_id)

    def test_service_and_book_switches_keep_separate_account_lists(self):
        page = self.page
        page.locator("#service").select_option("gemini")
        self.add("Book A Google")
        first_id = page.locator("#account-select").input_value()
        page.locator("#service").select_option("chatgpt")
        self.assertEqual(page.locator("#account-name").input_value(), "ChatGPT 1")
        page.locator("#service").select_option("gemini")
        self.assertEqual(page.locator("#account-select").input_value(), first_id)
        self.assertTrue(page.locator("#fallback").is_disabled())
        page.locator("#tab-book-2").click()
        page.locator("#service").select_option("gemini")
        self.assertEqual(page.locator("#account-count").text_content(), "1")
        self.add("Book B Google")
        page.locator("#tab-book-1").click()
        self.assertEqual(page.locator("#account-select").input_value(), first_id)
        self.assertEqual(page.locator("#account-name").input_value(), "Book A Google")
        self.assertEqual(page.locator("#account-count").text_content(), "2")
        self.assertNotEqual(self.manager.sessions["book-1"].settings["profile_dir"],
                            self.manager.sessions["book-2"].settings["profile_dir"])
        page.screenshot(path=str(PROJECT_ROOT.parent / "scratch/gemini-accounts-preview.png"), full_page=True)


if __name__ == "__main__":
    unittest.main()
