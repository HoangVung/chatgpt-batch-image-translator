"""Offline end-to-end report/CLI tests using tiny synthetic page images."""
import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from layout_pipeline import main, process_download_safely, process_page
from layout_profile import LayoutProfile


class LayoutPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_dir = self.root / "nguồn"
        self.generated_dir = self.root / "tiếng Việt"
        self.source_dir.mkdir()
        self.generated_dir.mkdir()
        self.source = self.source_dir / "1_1.png"
        self.generated = self.generated_dir / "00001_00001VN.png"
        image = Image.new("RGB", (80, 120), "white")
        ImageDraw.Draw(image).rectangle((10, 10, 69, 109), fill=(30, 40, 50))
        image.save(self.source)
        image.save(self.generated)
        image.close()
        self.profile = LayoutProfile(
            enabled=True, target_size=(100, 140), margins=(20, 20, 20, 20),
            output_dir=self.root / "kết quả", annotate=True,
        )
        self.config = self.root / "profile.json"
        self.config.write_text(json.dumps({
            "enabled": True, "target_size": [100, 140], "margins": [20, 20, 20, 20],
            "output_dir": "kết quả", "annotate": True,
        }), encoding="utf-8")

    def run_page(self, **changes):
        return process_page(self.source, self.generated, replace(self.profile, **changes),
                            logger=lambda message: None)

    def test_qc_only_writes_json_csv_and_annotation_without_touching_inputs(self):
        before = self.source.read_bytes(), self.generated.read_bytes()
        report = self.run_page(normalize_enabled=False)
        self.assertEqual(report["processing_status"], "COMPLETED", report)
        directory = Path(report["run_dir"])
        self.assertEqual(json.loads((directory / "report.json").read_text(encoding="utf-8"))
                         ["qc"]["status"], report["qc"]["status"])
        with (directory / "report.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["normalization_status"], "SKIPPED")
        self.assertTrue(Path(report["annotation"]).is_file())
        self.assertEqual(Path(report["original_copy"]).read_bytes(), before[1])
        self.assertEqual(before, (self.source.read_bytes(), self.generated.read_bytes()))
        self.assertFalse((directory / "normalized").exists())

    def test_normalized_png_preserves_every_original_pixel(self):
        before = self.generated.read_bytes()
        report = self.run_page()
        self.assertEqual(report["normalization"]["status"], "NORMALIZED", report)
        self.assertIn("normalized_qc", report)
        with Image.open(self.generated) as original, Image.open(report["normalized"]) as normalized:
            self.assertEqual(normalized.size, (100, 140))
            x, y = report["normalization"]["offset"]
            pasted = normalized.crop((x, y, x + original.width, y + original.height))
            self.assertEqual(pasted.tobytes(), original.tobytes())
        self.assertEqual(report["original_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(self.generated.read_bytes(), before)

    def test_repeated_runs_never_overwrite_previous_results(self):
        first = self.run_page()
        artifacts = {p: p.read_bytes() for p in Path(first["run_dir"]).rglob("*") if p.is_file()}
        second = self.run_page()
        self.assertNotEqual(first["run_dir"], second["run_dir"])
        self.assertTrue(artifacts)
        for path, data in artifacts.items():
            self.assertEqual(path.read_bytes(), data)

    def test_disabled_profile_does_not_touch_paths_or_create_output(self):
        profile = replace(self.profile, enabled=False)
        with patch("layout_pipeline.check_layout", side_effect=AssertionError("must not call")):
            report = process_page(self.root / "missing", self.root / "missing2", profile)
        self.assertEqual(report["processing_status"], "SKIPPED")
        self.assertFalse(self.profile.output_dir.exists())
        self.config.write_text('{"enabled":false}', encoding="utf-8")
        self.assertEqual(process_download_safely("missing", "missing2", self.config)
                         ["processing_status"], "SKIPPED")

    def test_bad_config_and_failing_logger_cannot_escape_worker_boundary(self):
        self.config.write_text("{bad", encoding="utf-8")
        def bad_logger(message):
            raise OSError("closed pipe")
        before = self.generated.read_bytes()
        report = process_download_safely(self.source, self.generated, self.config, logger=bad_logger)
        self.assertEqual(report["processing_status"], "ERROR")
        self.assertEqual(self.generated.read_bytes(), before)

    def test_normalizer_failure_keeps_download_and_records_error(self):
        before = self.generated.read_bytes()
        with patch("layout_normalizer.normalize_image", side_effect=OSError("simulated disk error")):
            report = self.run_page()
        self.assertEqual(report["processing_status"], "ERROR")
        self.assertEqual(Path(report["original_copy"]).read_bytes(), before)
        self.assertEqual(self.generated.read_bytes(), before)
        on_disk = json.loads((Path(report["run_dir"]) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["processing_status"], "ERROR")
        self.assertEqual(self.run_page()["processing_status"], "COMPLETED")

    def test_unwritable_output_and_report_errors_do_not_touch_original(self):
        before = self.generated.read_bytes()
        report = self.run_page(output_dir=self.generated)
        self.assertEqual(report["processing_status"], "ERROR")
        with patch("layout_pipeline._write_reports", side_effect=PermissionError("denied")):
            report = self.run_page(normalize_enabled=False)
        self.assertEqual(report["processing_status"], "ERROR")
        self.assertIn("report_error", report)
        self.assertEqual(self.generated.read_bytes(), before)

    def test_invalid_image_produces_fail_report_without_normalized_output(self):
        self.generated.write_bytes(b"not a raster")
        report = self.run_page()
        self.assertEqual(report["processing_status"], "ERROR")
        self.assertEqual(report["qc"]["status"], "FAIL")
        self.assertNotIn("normalized", report)
        self.assertEqual(self.generated.read_bytes(), b"not a raster")

    def test_invalid_source_prevents_normalization(self):
        self.source.write_bytes(b"corrupt source")
        report = self.run_page()
        self.assertEqual(report["processing_status"], "ERROR")
        self.assertNotIn("normalized", report)
        self.assertIn("INVALID_SOURCE", [f["code"] for f in report["qc"]["findings"]])

    def test_template_marks_relayout_without_creating_derivative(self):
        report = self.run_page(page_number_region=(40, 122, 60, 138))
        self.assertEqual(report["normalization"]["status"], "NEEDS_RELAYOUT")
        self.assertNotIn("normalized", report)
        self.assertTrue(Path(report["original_copy"]).exists())

    def write_progress(self, rows):
        path = self.generated_dir / "progress.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["index", "file", "output", "status", "time", "note"])
            writer.writerows(rows)
        return path

    def run_cli(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(["--profile", str(self.config), *map(str, args)])

    def test_cli_reads_latest_progress_and_never_rewrites_translation_state(self):
        progress = self.write_progress([
            [1, self.source.name, self.generated.name, "fail", "", ""],
            [1, self.source.name, self.generated.name, "done", "", "OK"],
            [2, "skipped.png", "missing.png", "fail", "", ""],
        ])
        before = progress.read_bytes()
        code = self.run_cli("--progress", progress, "--source-dir", self.source_dir,
                            "--generated-dir", self.generated_dir, "--qc-only")
        self.assertEqual(code, 1)  # Measured target-size/margin warnings, not a translation error.
        self.assertEqual(progress.read_bytes(), before)
        self.assertEqual(len(list(self.profile.output_dir.glob("page-*/report.json"))), 1)

    def test_cli_continues_after_bad_page_and_path_traversal(self):
        progress = self.write_progress([
            [1, "missing.png", "missing.png", "done", "", ""],
            [2, "../outside.png", self.generated.name, "done", "", ""],
            [3, self.source.name, self.generated.name, "done", "", ""],
        ])
        before = progress.read_bytes()
        code = self.run_cli("--progress", progress, "--source-dir", self.source_dir,
                            "--generated-dir", self.generated_dir)
        self.assertEqual(code, 2)
        reports = [json.loads(p.read_text(encoding="utf-8"))
                   for p in self.profile.output_dir.glob("page-*/report.json")]
        self.assertEqual({r["processing_status"] for r in reports}, {"ERROR", "COMPLETED"})
        self.assertEqual(progress.read_bytes(), before)

    def test_cli_rejects_missing_or_wrong_progress_schema(self):
        self.assertEqual(self.run_cli("--progress", self.root / "missing.csv",
                                     "--source-dir", self.source_dir,
                                     "--generated-dir", self.generated_dir), 2)
        bad = self.root / "bad.csv"
        bad.write_text("x,y\n1,2\n", encoding="utf-8")
        self.assertEqual(self.run_cli("--progress", bad, "--source-dir", self.source_dir,
                                     "--generated-dir", self.generated_dir), 2)

    def test_cli_single_page_qc_only_and_master_off(self):
        self.assertEqual(self.run_cli("--source", self.source, "--generated", self.generated,
                                     "--qc-only"), 1)
        self.config.write_text('{"enabled":false}', encoding="utf-8")
        self.assertEqual(self.run_cli("--source", self.root / "missing",
                                     "--generated", self.root / "missing2"), 0)


if __name__ == "__main__":
    unittest.main()
