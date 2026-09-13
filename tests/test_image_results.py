"""Browser regressions for generated-image detection and saving; no live account needed.

Install requirements and Chromium first. BATCH_TEST_BROWSER can select an existing
Chrome/Chromium executable instead of the Playwright-managed browser.
"""
import base64
import csv
import importlib.util
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def image_bytes(fmt="PNG", size=(320, 240)):
    output = BytesIO()
    Image.new("RGB", size, (20, 100, 180)).save(output, format=fmt)
    return output.getvalue()


def image_url(fmt="PNG", size=(320, 240)):
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(image_bytes(fmt, size)).decode()


class ImageResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            pw_manager = sync_playwright()
            if pw_manager is None or not hasattr(pw_manager, "start"):
                raise ImportError("Playwright is not available or mocked")
        except (ImportError, AttributeError):
            raise unittest.SkipTest("Playwright is required for browser image tests")
        spec = importlib.util.spec_from_file_location("image_worker", PROJECT_ROOT / "run_chatgpt_batch.py")
        cls.worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.worker)
        cls.playwright = pw_manager.start()
        try:
            options = {"headless": True}
            if os.environ.get("BATCH_TEST_BROWSER"):
                options["executable_path"] = os.environ["BATCH_TEST_BROWSER"]
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
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.page.close)
        self.destination = Path(self.directory.name) / "Ảnh tiếng Việt có dấu" / "00026_00039VN.png"

    def show(self, html):
        self.page.set_content(html)
        self.page.wait_for_function("Array.from(document.images).every(img => img.complete)")

    def assert_saved_png(self, size=(320, 240)):
        self.assertTrue(self.worker.is_valid_image_file(self.destination))
        with Image.open(self.destination) as saved:
            self.assertEqual(saved.format, "PNG")
            self.assertEqual(saved.size, size)
        self.assertFalse(Path(str(self.destination) + ".part").exists())

    def test_chatgpt_image_tool_sibling_is_detected_without_selecting_uploads(self):
        generated, old = image_url(), image_url(size=(100, 100))
        self.show(f"""
            <aside><img src="{image_url(size=(110, 110))}"></aside>
            <article data-testid="conversation-turn-1" data-turn="user">
                <div data-message-author-role="user">Upload</div>
                <div><img src="{image_url(size=(120, 120))}"></div>
            </article>
            <article data-testid="conversation-turn-2">
                <div data-message-author-role="assistant"><img src="{old}"></div>
            </article>
            <article data-testid="conversation-turn-3" data-turn="assistant">
                <div data-message-author-role="assistant">Đã tạo ảnh</div>
                <div class="image-tool"><img src="{generated}"></div>
            </article>
            <form><div id="prompt-textarea" contenteditable="true"></div>
                <img src="{image_url(size=(130, 130))}"></form>
        """)
        self.assertEqual(self.worker.get_all_image_srcs(self.page), [old, generated])
        self.assertEqual(self.worker.get_latest_new_image(self.page, [old]), generated)

    def test_tool_only_conversation_turn_and_gemini_response(self):
        for wrapper in (
            '<article data-testid="conversation-turn-7">{}</article>',
            '<model-response><message-content>Đã tạo ảnh</message-content>{}</model-response>',
        ):
            with self.subTest(wrapper=wrapper):
                url = image_url()
                self.show(wrapper.format(f'<div><img src="{url}"></div>'))
                self.assertEqual(self.worker.get_all_image_srcs(self.page), [url])

    def test_hidden_old_image_does_not_become_a_new_result_when_shown(self):
        url = image_url()
        self.show(f'<article data-turn="assistant"><img style="display:none" src="{url}"></article>')
        self.assertEqual(self.worker.get_all_image_srcs(self.page), [])
        baseline = self.worker.get_all_image_srcs(self.page, include_pending=True)
        self.page.locator("img").evaluate("img => img.style.display = 'block'")
        self.assertEqual(baseline, [url])
        self.assertIsNone(self.worker.get_latest_new_image(self.page, baseline))

    def test_icons_and_hidden_images_are_not_results(self):
        self.show(f"""<article data-turn="assistant">
            <img alt="avatar" src="{image_url()}">
            <img src="{image_url(size=(32, 32))}">
            <img style="visibility:hidden" src="{image_url(size=(200, 200))}">
        </article>""")
        self.assertEqual(self.worker.get_all_image_srcs(self.page), [])

    def test_data_and_blob_images_are_saved_as_real_png_in_unicode_directory(self):
        for fmt in ("PNG", "JPEG", "WEBP"):
            for blob in (False, True):
                with self.subTest(fmt=fmt, blob=blob):
                    url = image_url(fmt)
                    if blob:
                        url = self.page.evaluate("async u => URL.createObjectURL(await (await fetch(u)).blob())", url)
                    self.worker.download_image(self.page, url, str(self.destination))
                    self.assert_saved_png()
        # Valid compressed images may be well below the previous 10 KB threshold.
        self.assertLess(self.destination.stat().st_size, 10000)

    def test_cross_origin_image_download_uses_authenticated_request_fallback(self):
        payload = image_bytes()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                if self.path == "/image.png":
                    self.send_header("Content-Type", "image/png")
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<!doctype html><body>Local image test</body>")

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            port = server.server_port
            self.page.goto(f"http://localhost:{port}/page")
            url = f"http://127.0.0.1:{port}/image.png"
            with patch.object(self.worker, "fetch_image_with_session", wraps=self.worker.fetch_image_with_session) as fallback:
                self.worker.download_image(self.page, url, str(self.destination))
                fallback.assert_called_once()
            self.assert_saved_png()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_loaded_pixels_fallback_keeps_natural_resolution(self):
        url = image_url(size=(800, 600))
        self.show(f'<article data-turn="assistant"><img width="100" src="{url}"></article>')
        with patch.object(self.worker, "fetch_image_in_browser", side_effect=RuntimeError("unavailable")):
            self.worker.download_image(self.page, url, str(self.destination))
        self.assert_saved_png(size=(800, 600))

    def test_invalid_download_preserves_existing_file(self):
        self.destination.parent.mkdir()
        existing = image_bytes()
        self.destination.write_bytes(existing)
        with patch.object(self.worker, "fetch_image_in_browser", return_value=b"<html>error</html>"), patch.object(self.worker, "read_loaded_image", side_effect=ValueError("missing")):
            with self.assertRaises(RuntimeError):
                self.worker.download_image(self.page, "blob:invalid", str(self.destination))
        self.assertEqual(self.destination.read_bytes(), existing)
        self.assertFalse(Path(str(self.destination) + ".part").exists())
        self.destination.write_bytes(b"<html>error</html>" * 1000)
        self.assertFalse(self.worker.is_valid_image_file(self.destination))

    def test_process_one_saves_to_configured_folder_before_marking_done(self):
        source = Path("26_039.jpg")
        url = image_url()
        progress = self.destination.parent / "progress.csv"
        with patch.multiple(
            self.worker, DOWNLOAD_FOLDER=str(self.destination.parent),
            PROGRESS_FILE=str(progress), SERVICE="chatgpt",
        ), patch.object(self.worker, "reset_chat"), patch.object(self.worker, "upload_image"), \
            patch.object(self.worker, "wait_upload_attached"), patch.object(self.worker, "run_dich_step", return_value=True), \
            patch.object(self.worker, "sleep"), patch.object(self.worker, "try_create_image", return_value=url):
            self.worker.process_one(self.page, {source: 1}, source)
        self.assert_saved_png()
        with progress.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "done")
        self.assertEqual(rows[0]["file"], "26_039.jpg")
        self.assertEqual(rows[0]["output"], self.destination.name)

    def test_missing_source_directory_stops_before_creating_output(self):
        with patch.multiple(
            self.worker, IMAGE_FOLDER=str(Path(self.directory.name) / "missing-input"),
            DOWNLOAD_FOLDER=str(self.destination.parent),
        ):
            with self.assertRaisesRegex(ValueError, "thư mục ảnh gốc"):
                self.worker.ensure_dirs()
        self.assertFalse(self.destination.parent.exists())

    def test_output_permission_error_names_the_path_and_cleans_partial_file(self):
        with patch.object(self.worker.os, "replace", side_effect=PermissionError("access denied")):
            with self.assertRaises(OSError) as error:
                self.worker.download_image(self.page, image_url(), str(self.destination))
        self.assertIn(str(self.destination), str(error.exception))
        self.assertFalse(self.destination.exists())
        self.assertFalse(Path(str(self.destination) + ".part").exists())


if __name__ == "__main__":
    unittest.main()
