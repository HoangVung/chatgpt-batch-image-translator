"""Trusted Chromium touch input against window chrome; no real worker or profile."""
import json
import tempfile
import unittest
from pathlib import Path

import test_web_frontend as frontend
from desktop.workflow_sessions import SessionManager
from desktop.webview_app import WebBridge


class WindowTouchTests(unittest.TestCase):
    setUpClass = classmethod(frontend.WebFrontendTests.setUpClass.__func__)
    tearDownClass = classmethod(frontend.WebFrontendTests.tearDownClass.__func__)

    def test_touch_drag_capture_release_cancel_and_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(app_dir=frontend.PROJECT_ROOT, data_dir=Path(directory))
            try:
                initial = manager._invoke("get_initial_state")["data"]
                # Window moves remain global even when workflows share the shell.
                positions = []
                from types import SimpleNamespace
                manager._attach_window(SimpleNamespace(move=lambda x, y: positions.append((x, y))))
                self.assertTrue(WebBridge(manager).move_window(-100, 40)["ok"])
                self.assertEqual(positions, [(-100, 40)])
            finally:
                manager._shutdown()

        page = self.browser.new_page(has_touch=True, viewport={"width": 1180, "height": 700})
        self.addCleanup(page.close)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("""
            window.moves = []; window.controls = [];
            const ok = data => Promise.resolve({ok:true, data:data || {}});
            window.pywebview = {api: {
                get_initial_state: () => ok(%s),
                move_window: (x,y) => { moves.push([x,y]); return ok(); },
                minimize_window: () => { controls.push('minimize'); return ok(); }
            }};
        """ % json.dumps(initial))
        page.goto(self.ui_url)
        page.wait_for_function("document.querySelector('#status').textContent === 'Sẵn sàng'")
        cdp = page.context.new_cdp_session(page)

        def touch(kind, x=300, y=18):
            cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints":
                [] if kind in ("touchEnd", "touchCancel") else [{"x": x, "y": y}]})

        # A held finger can leave the 38px titlebar without becoming a page pan.
        touch("touchStart")
        touch("touchMove", 350, 100)
        touch("touchMove", 380, 140)
        touch("touchEnd")
        page.wait_for_function("moves.length >= 2")
        moves = page.evaluate("moves")
        self.assertEqual([moves[-1][i] - moves[0][i] for i in (0, 1)], [30, 40])
        self.assertEqual(page.evaluate("window.scrollY"), 0)
        self.assertFalse(page.evaluate("!!chromeDrag"))

        # A fresh gesture in the content must not continue moving the window.
        count = len(moves)
        touch("touchStart", 600, 400)
        touch("touchMove", 600, 300)
        touch("touchEnd")
        self.assertEqual(page.evaluate("moves.length"), count)

        touch("touchStart")
        touch("touchMove", 320, 50)
        touch("touchCancel")
        self.assertFalse(page.evaluate("!!chromeDrag"))
        count = page.evaluate("moves.length")
        page.locator(".tl-minimize").tap()
        page.wait_for_function("controls.includes('minimize')")
        self.assertEqual(page.evaluate("moves.length"), count)
        page.evaluate("document.body.classList.add('is-maximized')")
        touch("touchStart")
        touch("touchMove", 320, 50)
        touch("touchEnd")
        self.assertEqual(page.evaluate("moves.length"), count)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
