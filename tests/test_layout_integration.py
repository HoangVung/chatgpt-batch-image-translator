"""Exercise both post-download hooks without importing browser workers or using quota.

Only process_one and its real image validator are compiled from each worker.
Browser actions are recording doubles; generated files are real PNG fixtures.
"""
import ast
import builtins
import json
from io import BytesIO
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WorkerLayoutMixin:
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.downloads = self.root / "downloaded"
        self.downloads.mkdir()
        fixture = BytesIO()
        Image.new("RGB", (160, 240), "white").save(fixture, format="PNG")
        self.original_bytes = fixture.getvalue()
        self.source = self.root / "page001.png"
        self.source.write_bytes(self.original_bytes)
        self.events = []
        self.progress = []
        self.layout_imports = []
        self.layout_error = None
        self.import_error = None
        self.download_error = None
        self.download_bytes = self.original_bytes
        self.environ = {}
        self.messages = Mock()
        self.layout = Mock(side_effect=self._layout)
        self.page = object()

        source = (PROJECT_ROOT / self.WORKER).read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=self.WORKER)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {"process_one", "is_valid_image_file"}]
        self.assertEqual(len(functions), 2)
        safe_builtins = dict(vars(builtins), __import__=self._import)
        self.namespace = {
            "__builtins__": safe_builtins,
            "Image": Image,
            "os": SimpleNamespace(path=os.path, environ=self.environ),
            "SERVICE": "chatgpt",
            "DOWNLOAD_FOLDER": str(self.downloads),
            "get_output_name": lambda img: img.stem + "VN.png",
            "print": self.messages,
            "reset_chat": self._record("reset"),
            "upload_image": self._record("upload"),
            "wait_upload_attached": self._record("attached"),
            "run_dich_step": self._record("translate", True),
            "sleep": self._record("sleep"),
            "get_all_image_srcs": self._record("images", ["old-image"]),
            "try_create_image": self._record("create", "generated-image"),
            "download_image": self._download,
            "download_gemini_image": self._download_gemini,
            "write_progress": self._write_progress,
        }
        isolated = ast.Module(body=functions, type_ignores=[])
        exec(compile(isolated, self.WORKER, "exec"), self.namespace)
        validator = self.namespace["is_valid_image_file"]

        def validate(path):
            self.events.append("validate")
            return validator(path)

        self.namespace["is_valid_image_file"] = validate
        self.process = self.namespace["process_one"]

    def _record(self, name, result=None):
        def callback(*args, **kwargs):
            self.events.append(name)
            return result
        return callback

    def _import(self, name, *args, **kwargs):
        if name != "layout_pipeline":
            return builtins.__import__(name, *args, **kwargs)
        self.layout_imports.append(name)
        if self.import_error is not None:
            raise self.import_error
        return SimpleNamespace(process_download_safely=self.layout)

    def _download(self, page, url, destination):
        self.assertIs(page, self.page)
        self.events.append("download")
        if self.download_error is not None:
            raise self.download_error
        Path(destination).write_bytes(self.download_bytes)

    def _download_gemini(self, page, destination, url):
        self.events.append("gemini")
        self._download(page, url, destination)

    def _write_progress(self, *row):
        self.events.append("done")
        self.progress.append(row)

    def _layout(self, source, generated, profile_path):
        self.assertEqual(self.events[-1], "done")
        self.assertEqual(self.progress[-1][3:], ("done", "OK"))
        self.assertEqual(Path(generated).read_bytes(), self.original_bytes)
        self.assertEqual(Path(source).read_bytes(), self.original_bytes)
        self.assertEqual(profile_path, "book-layout.json")
        self.events.append("layout")
        if self.layout_error is not None:
            raise self.layout_error
        return {"status": "PASS"}

    def run_page(self, source=None, index=1):
        source = source or self.source
        self.process(self.page, {source: index}, source)
        return self.downloads / (source.stem + "VN.png")

    def enable_layout(self):
        self.environ["BATCH_LAYOUT_PROFILE"] = "book-layout.json"

    def assert_two_pages_complete(self):
        second = self.root / "page002.png"
        second.write_bytes(self.original_bytes)
        paths = [self.run_page(), self.run_page(second, 2)]
        self.assertEqual(self.progress, [
            (1, "page001.png", "page001VN.png", "done", "OK"),
            (2, "page002.png", "page002VN.png", "done", "OK"),
        ])
        for path in paths + [self.source, second]:
            self.assertEqual(path.read_bytes(), self.original_bytes)
        self.assertEqual(self.events.count("create"), 2)
        self.assertEqual(self.events.count("download"), 2)

    def test_off_has_no_layout_import_or_extra_files_and_keeps_workflow_order(self):
        output = self.run_page()
        self.assertEqual(self.events, [
            "reset", "upload", "attached", "translate", "sleep", "images",
            "create", "download", "validate", "done",
        ])
        self.assertEqual(self.layout_imports, [])
        self.layout.assert_not_called()
        self.assertEqual(list(self.downloads.iterdir()), [output])
        self.assertEqual({p.relative_to(self.root).as_posix()
                          for p in self.root.rglob("*") if p.is_file()},
                         {"page001.png", "downloaded/page001VN.png"})
        self.assertEqual(self.source.read_bytes(), self.original_bytes)
        self.assertEqual(output.read_bytes(), self.original_bytes)

    def test_empty_profile_flag_is_off(self):
        self.environ["BATCH_LAYOUT_PROFILE"] = ""
        self.run_page()
        self.assertEqual(self.layout_imports, [])
        self.layout.assert_not_called()

    def test_on_runs_only_after_saved_image_validation_and_done(self):
        self.enable_layout()
        output = self.run_page()
        self.assertEqual(self.events[-4:], ["download", "validate", "done", "layout"])
        self.layout.assert_called_once_with(self.source, str(output), "book-layout.json")
        self.assertEqual(self.events.count("create"), 1)
        self.assertEqual(self.events.count("translate"), 1)
        self.assertEqual(output.read_bytes(), self.original_bytes)

    def test_postprocessing_error_keeps_done_originals_and_next_page(self):
        self.enable_layout()
        self.layout_error = RuntimeError("postprocessing failed")
        self.assert_two_pages_complete()
        self.assertEqual(self.layout.call_count, 2)

    def test_import_error_keeps_done_originals_and_next_page(self):
        self.enable_layout()
        self.import_error = ImportError("optional layout module unavailable")
        self.assert_two_pages_complete()
        self.assertEqual(len(self.layout_imports), 2)
        self.layout.assert_not_called()

    def test_invalid_download_never_runs_postprocessing_or_marks_done(self):
        self.enable_layout()
        self.download_bytes = b"<html>download failed</html>"
        with self.assertRaises(Exception):
            self.run_page()
        self.assertEqual(self.progress, [])
        self.assertEqual(self.layout_imports, [])
        self.layout.assert_not_called()
        self.assertEqual(self.source.read_bytes(), self.original_bytes)

    def test_download_exception_never_runs_postprocessing(self):
        self.enable_layout()
        self.download_error = OSError("disk unavailable")
        with self.assertRaisesRegex(OSError, "disk unavailable"):
            self.run_page()
        self.assertEqual(self.progress, [])
        self.assertEqual(self.layout_imports, [])
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_gemini_ignores_chatgpt_layout_flag(self):
        self.enable_layout()
        self.namespace["SERVICE"] = "gemini"
        self.run_page()
        self.assertIn("gemini", self.events)
        self.assertEqual(self.layout_imports, [])
        self.layout.assert_not_called()
        self.assertEqual(self.progress[0][3:], ("done", "OK"))


    def _assert_real_unattended_qc(self, normalize, expected_state):
        from layout_pipeline import process_download_safely
        self.enable_layout()
        profile = self.root / "unattended-layout.json"
        profile.write_text(json.dumps({
            "enabled": True, "source_aware_enabled": True,
            "normalize_enabled": normalize,
            "output_dir": str(self.root / "qc-reports"),
        }), encoding="utf-8")
        reports = []

        def actual_layout(source, generated, profile_path):
            self._layout(source, generated, profile_path)
            report = process_download_safely(source, generated, profile, logger=lambda _: None)
            reports.append(report)
            return report

        self.layout.side_effect = actual_layout
        with patch("builtins.input", side_effect=AssertionError("QC must not request input")):
            self.assert_two_pages_complete()
        self.assertEqual(len(reports), 2)
        for report in reports:
            self.assertEqual(report["processing_status"], "COMPLETED", report)
            self.assertEqual(report["qc"]["source_aware"]["status"], expected_state)
            self.assertEqual(report["metadata"]["pairing_method"], "worker")
            self.assertNotIn("page_number", report["metadata"])
            self.assertFalse(report["automation"]["blocks_batch"])
            self.assertFalse(report["automation"]["manual_action_required"])
            self.assertEqual(report["automation"]["next_action"], "continue")
            self.assertTrue((Path(report["run_dir"]) / "report.json").is_file())

    def test_real_source_qc_uncertain_result_never_waits_or_retries_translation(self):
        self._assert_real_unattended_qc(False, "REVIEW_REQUIRED")

    def test_real_source_qc_unfixable_layout_keeps_original_and_continues(self):
        self._assert_real_unattended_qc(True, "NEEDS_RELAYOUT")


class PrimaryWorkerLayoutTests(WorkerLayoutMixin, unittest.TestCase):
    WORKER = "run_chatgpt_batch.py"


class Books34WorkerLayoutTests(WorkerLayoutMixin, unittest.TestCase):
    WORKER = "run_chatgpt_batch_books34.py"


if __name__ == "__main__":
    unittest.main()