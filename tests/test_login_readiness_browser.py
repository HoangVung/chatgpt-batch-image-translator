"""Real browser DOM for manual Continue; isolated context, no account/network."""
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from test_login_flow import WORKERS, Clock

WORKER = WORKERS[0]
GUEST = '<button>Log in</button><div id="prompt-textarea" contenteditable="true"></div>'
READY = '<div id="prompt-textarea" contenteditable="true"></div>'
CHALLENGE = '<h1>Verify you are human</h1>'


class LoginReadinessBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
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
        self.context.route('**/*', lambda route: route.fulfill(
            status=200, content_type='text/html', body=GUEST))
        self.page = self.context.new_page()
        self.page.goto('https://chatgpt.com/')
        self.clock = Clock()

    def run_login(self, continuation, tick=None):
        def sleep(seconds):
            self.clock.advance(seconds)
            if tick:
                tick()
        with patch.object(WORKER.time, 'monotonic', side_effect=lambda: self.clock.now), \
             patch.object(WORKER, 'sleep', side_effect=sleep), \
             patch.object(WORKER, 'check_stop_requested'), \
             patch.object(WORKER, 'print'), \
             patch.object(WORKER, 'wait_for_continue', side_effect=continuation) as wait:
            result = WORKER.login_if_needed(self.page)
        wait.assert_called_once()
        return result

    def test_continue_selects_ready_new_tab_while_original_stays_guest(self):
        selected = []
        def continuation(_prompt):
            tab = self.context.new_page()
            tab.goto('https://chatgpt.com/')
            tab.set_content(READY)
            selected.append(tab)
        self.assertIs(self.run_login(continuation), selected[0])
        self.assertTrue(WORKER.has_signin_prompt(self.page))

    def test_continue_waits_through_challenge_and_slow_signin_ui(self):
        continued = []
        def continuation(_prompt):
            continued.append(self.clock.now)
            self.page.set_content(CHALLENGE)
        def tick():
            if continued:
                elapsed = self.clock.now - continued[0]
                self.page.set_content(READY if elapsed >= 12 else GUEST if elapsed >= 6 else CHALLENGE)
        self.assertIs(self.run_login(continuation, tick), self.page)
        self.assertGreaterEqual(self.clock.now - continued[0], 12)

    def test_conversation_verification_words_are_not_cloudflare(self):
        self.page.set_content(READY + '<article>Cloudflare: Verify you are human. Just a moment.</article>')
        self.assertFalse(WORKER.is_cloudflare(self.page))

    def test_personalized_login_suggestions_do_not_request_signin(self):
        suggestions = (
            '<button>Meta vừa báo đăng nhập Windows mới: Đối chiếu chuỗi cảnh báo</button>'
            '<a href="#">Review your Log in notifications</a>'
        )
        self.context.unroute('**/*')
        self.context.route('**/*', lambda route: route.fulfill(
            status=200, content_type='text/html', body=READY + suggestions))
        with patch.object(WORKER.time, 'monotonic', side_effect=lambda: self.clock.now), \
             patch.object(WORKER, 'sleep', side_effect=self.clock.advance), \
             patch.object(WORKER, 'check_stop_requested'), patch.object(WORKER, 'print'), \
             patch.object(WORKER, 'wait_for_continue') as wait:
            self.assertIs(WORKER.login_if_needed(self.page), self.page)
        wait.assert_not_called()
        self.assertFalse(WORKER.has_signin_prompt(self.page))

    def test_exact_signin_labels_still_block_guest_composer(self):
        for tag, label in [('button', 'Đăng nhập'), ('a', 'Log in'), ('button', 'Sign in')]:
            with self.subTest(tag=tag, label=label):
                self.page.set_content(READY + f'<{tag} href="#"><span>{label}</span></{tag}>')
                self.assertTrue(WORKER.has_signin_prompt(self.page))

    def test_worker_viewport_keeps_account_menu_inside_resized_window(self):
        def launch(**options):
            options["headless"] = True
            options["args"] += ["--window-size=1400,900"]
            return self.playwright.chromium.launch_persistent_context(**options)
        wrapper = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
        with TemporaryDirectory() as profile:
            context = WORKER.launch_persistent_context(wrapper, profile)
            try:
                page = context.pages[0]
                page.set_content('<div id="account" style="position:fixed;bottom:0;height:40px">Account</div>')
                cdp = context.new_cdp_session(page)
                window = cdp.send('Browser.getWindowForTarget')
                cdp.send('Browser.setWindowBounds', {
                    'windowId': window['windowId'], 'bounds': {'width': 1100, 'height': 700},
                })
                page.wait_for_function('innerHeight === 700 && innerWidth === 1100')
                geometry = page.evaluate("""() => ({innerHeight, outerHeight,
                    footerBottom: document.querySelector('#account').getBoundingClientRect().bottom})""")
                self.assertLessEqual(geometry['footerBottom'], geometry['outerHeight'])
                self.assertEqual(geometry['footerBottom'], geometry['innerHeight'])
            finally:
                context.close()

    def test_guest_composer_still_fails_after_full_manual_timeout(self):
        with self.assertRaisesRegex(Exception, 'chưa đăng nhập'):
            self.run_login(lambda _prompt: None)
        self.assertGreaterEqual(self.clock.now, 94)


if __name__ == '__main__':
    unittest.main()
