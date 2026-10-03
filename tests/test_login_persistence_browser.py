"""Exercise app shutdown and reopen with a real browser and synthetic session only."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_controller import DesktopController, ProcessLaunch, Scheduler


WORKER = r'''
import importlib
import os
from pathlib import Path
from types import SimpleNamespace
from playwright.sync_api import sync_playwright
from resource_guard import ResourceLease, workflow_resources
from worker_control import WorkerStopRequested, cooperative_sleep, wait_for_continue

worker = importlib.import_module(os.environ["TEST_WORKER"])
profile = os.environ["TEST_PROFILE"]
settings = {"profile_dir": profile, "service": "chatgpt"}
try:
    with ResourceLease(workflow_resources(settings, "login")):
        with sync_playwright() as p:
            def launch(**kwargs):
                kwargs["headless"] = True
                if os.environ.get("BATCH_TEST_BROWSER"):
                    kwargs["executable_path"] = os.environ["BATCH_TEST_BROWSER"]
                return p.chromium.launch_persistent_context(**kwargs)
            wrapper = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
            context = worker.launch_persistent_context(wrapper, profile)
            try:
                context.route("https://profile-persistence.invalid/**", lambda route: route.fulfill(
                    status=200, content_type="text/html", body="<html>Local profile fixture</html>"))
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://profile-persistence.invalid/")
                if os.environ["TEST_PHASE"] == "write":
                    context.add_cookies([{"name": "synthetic_session", "value": "fixture-value",
                        "url": "https://profile-persistence.invalid/", "expires": 4102444800}])
                    page.evaluate("localStorage.setItem('synthetic_login', 'fixture-user')")
                    print("PROFILE_TEST_READY", flush=True)
                    if os.environ["TEST_WAIT"] == "manual":
                        wait_for_continue("Fixture login waiting: ")
                    else:
                        cooperative_sleep(120)
                    raise AssertionError("Stop must interrupt the fixture wait")
                else:
                    cookies = {item["name"]: item["value"] for item in context.cookies()}
                    assert cookies.get("synthetic_session") == "fixture-value"
                    assert page.evaluate("localStorage.getItem('synthetic_login')") == "fixture-user"
                    print("PROFILE_TEST_RESTORED", flush=True)
            finally:
                context.close()
                print("PROFILE_TEST_CLOSED", flush=True)
except WorkerStopRequested:
    raise SystemExit(130)
'''


class NoTimers(Scheduler):
    def call_later(self, delay_ms, callback):
        raise AssertionError("Fixture must not schedule a batch")

    def cancel(self, handle):
        pass


class BrowserLoginPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        # The fixture overrides LOCALAPPDATA for lock/test isolation, so point
        # Playwright at the real browser install explicitly.
        cls.browsers_path = str(
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ms-playwright"
        )
        manager = sync_playwright()
        playwright = manager.start()
        try:
            cls.browser_executable = playwright.chromium.executable_path
        finally:
            playwright.stop()

    def wait_for_log(self, controller, marker):
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            controller.drain_events()
            if marker in "".join(controller.log_history):
                return
            if not controller.is_running():
                break
            time.sleep(0.05)
        self.fail("Expected " + marker + "\n" + "".join(controller.log_history))

    def test_shutdown_saves_session_and_reopen_restores_both_workers(self):
        for module, wait_mode in (("run_chatgpt_batch", "manual"),
                                  ("run_chatgpt_batch_books34", "sleep")):
            with self.subTest(worker=module), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                script = base / "browser_worker.py"
                script.write_text(WORKER, encoding="utf-8")
                profile = base / "My Drive" / "profile fixture"
                forced = []
                processes = []

                def force_stop(process):
                    forced.append(process.pid)
                    DesktopController._terminate_process_tree(process)

                controller = DesktopController(NoTimers(), process_tree_terminator=force_stop)
                env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8",
                           LOCALAPPDATA=str(base / "local"), TEST_WORKER=module,
                           TEST_PROFILE=str(profile), TEST_PHASE="write", TEST_WAIT=wait_mode,
                           PLAYWRIGHT_BROWSERS_PATH=self.browsers_path,
                           BATCH_TEST_BROWSER=self.browser_executable)
                env.pop("BATCH_TRANSLATOR_SETTINGS_FILE", None)
                launch = ProcessLaunch([sys.executable, "-u", str(script)], str(ROOT), env,
                                       getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    self.assertTrue(controller.start("login", launch))
                    processes.append(controller.process)
                    self.wait_for_log(controller, "PROFILE_TEST_READY")
                    first = controller.process
                    controller.shutdown()
                    first.wait(timeout=15)
                    self.wait_for_log(controller, "PROFILE_TEST_CLOSED")
                    self.assertEqual(first.returncode, 130)
                    self.assertEqual(forced, [], "Browser should close without a forced kill")
                    env["TEST_PHASE"] = "read"
                    self.assertTrue(controller.start("login", launch))
                    second = controller.process
                    processes.append(second)
                    second.wait(timeout=35)
                    self.wait_for_log(controller, "PROFILE_TEST_RESTORED")
                    self.assertEqual(second.returncode, 0)
                finally:
                    controller.shutdown()
                    for process in processes:
                        process.wait(timeout=15)
                        for stream in (process.stdin, process.stdout, process.stderr):
                            if stream is not None:
                                stream.close()


if __name__ == "__main__":
    unittest.main()
