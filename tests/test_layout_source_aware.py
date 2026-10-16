"""Source-aware QC checks on synthetic rasters only; no provider or sample-book claims."""
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from layout_profile import LayoutProfile, load_profile
from layout_qc import check_layout


class SourceAwareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = LayoutProfile(
            enabled=True, source_aware_enabled=True, normalize_enabled=False,
            target_size=(600, 900), margins=(35, 30, 35, 35),
            output_dir=self.root / "reports", annotate=True,
        )

    def page(self, name="source.png", *, header_y=45, left=55, right=545,
             sparse=False, geometry=True, header_side="right", footer_side="right",
             edge_geometry=False):
        """Glyph-like blocks, line geometry and a distinct isolated formula surrogate."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with Image.new("RGB", (600, 900), "white") as image:
            draw = ImageDraw.Draw(image)

            def glyph_row(x, y, width, height=10):
                for index, start in enumerate(range(x, x + width - 7, 12)):
                    draw.rectangle((start, y, start + 6, y + height - index % 3), fill="black")

            header_x = 330 if header_side == "right" else 55
            glyph_row(header_x, header_y, 215, height=11)
            draw.line((55, header_y + 22, 545, header_y + 22), fill="black", width=2)
            for y in (155, 180, 205) if sparse else (155, 180, 205, 230, 255):
                glyph_row(left, y, right - left)
            if not sparse:
                if geometry:
                    x0, y0, x1, y1 = (0, 405, 190, 610) if edge_geometry else (100, 405, 290, 610)
                    points = [(x0 + (x1 - x0) // 2, y0), (x0, y1), (x1, y1)]
                    draw.line(points + points[:1], fill="black", width=3)
                    draw.line((points[0], ((x0 + x1) // 2, y1)), fill="black", width=2)
                glyph_row(340, 435, 170)
                glyph_row(340, 460, 170)
                glyph_row(200, 700, 180, height=14)
                draw.line((235, 697, 270, 697), fill="black", width=2)
                for y in (755, 780):
                    glyph_row(left, y, right - left)
            footer_x = 527 if footer_side == "right" else 55
            glyph_row(footer_x, 850, 20, height=13)
            image.save(path)
        return path

    @staticmethod
    def codes(result):
        return {item["code"] for item in result["findings"]}

    def compare(self, source, translated, **kwargs):
        return check_layout(source, translated, kwargs.pop("profile", self.profile), **kwargs)

    def test_flag_defaults_off_and_rejects_nonboolean(self):
        self.assertFalse(LayoutProfile().source_aware_enabled)
        for bad in ("true", 1, None):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                LayoutProfile(source_aware_enabled=bad)

    def test_threshold_and_alignment_validation(self):
        for changes in ({"source_thresholds": {"min_confidence": 1.1}},
                        {"source_thresholds": {"unknown": 0.1}},
                        {"source_thresholds": {"density_warning": float("nan")}},
                        {"mirrored_layout": "yes"}, {"header_alignment": "guess"},
                        {"footer_alignment": "right"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.profile, **changes)

    def test_source_profile_json_resolves_sample_and_preserves_old_fields(self):
        path = self.root / "profile.json"
        path.write_text(json.dumps({
            "enabled": True, "source_aware_enabled": True,
            "approved_sample": "sample.png", "sample_page_number": 9,
            "canonical_header": "Chương 1. Hình học phẳng",
            "header_alignment": "mirrored", "footer_alignment": "center",
            "source_thresholds": {"min_confidence": 0.8},
        }), encoding="utf-8")
        profile = load_profile(path)
        self.assertEqual(profile.approved_sample, self.root / "sample.png")
        self.assertEqual(profile.source_thresholds["min_confidence"], 0.8)
        self.assertIn("aspect_warning", profile.source_thresholds)
        self.assertTrue(profile.source_aware_enabled)
        self.assertEqual(profile.sample_page_number, 9)

    def test_off_keeps_legacy_comparison_informational(self):
        source, generated = self.page(), self.page("translated.png")
        result = self.compare(source, generated, profile=replace(self.profile, source_aware_enabled=False))
        self.assertNotIn("source_aware", result)
        self.assertFalse(result["metrics"]["source_comparison"]["affects_status"])

    def test_qc_off_does_not_open_images_even_when_source_feature_on(self):
        with patch("layout_qc._ink_mask", side_effect=AssertionError("must not open")):
            result = self.compare("missing-source", "missing-translated",
                                  profile=replace(self.profile, qc_enabled=False))
        self.assertEqual(result["status"], "SKIPPED")

    def test_missing_source_is_review_and_preserves_generated(self):
        generated = self.page("translated.png")
        before = generated.read_bytes()
        result = self.compare(self.root / "missing.png", generated)
        self.assertNotEqual(result["status"], "FAIL", result)
        self.assertEqual(result["source_aware"]["status"], "REVIEW_REQUIRED")
        self.assertEqual(before, generated.read_bytes())

    def test_unreadable_translated_still_fails(self):
        source = self.page()
        generated = self.root / "bad.png"
        generated.write_bytes(b"not an image")
        result = self.compare(source, generated)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("INVALID_GENERATED", self.codes(result))

    def test_comparison_never_modifies_inputs_and_is_json_serializable(self):
        source, generated = self.page(), self.page("translated.png")
        before = [hashlib.sha256(path.read_bytes()).digest() for path in (source, generated)]
        result = self.compare(source, generated, metadata={"page_number": 9})
        json.dumps(result, allow_nan=False)
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).digest() for path in (source, generated)])
        self.assertIn(result["source_aware"]["status"], {"PASS", "WARNING", "REVIEW_REQUIRED"})

    def test_conflicting_pair_metadata_fails_without_comparison(self):
        result = self.compare(self.page(), self.page("translated.png"), metadata={
            "source_page_number": 9, "generated_page_number": 10,
        })
        self.assertEqual(result["source_aware"]["status"], "FAIL")
        self.assertEqual(result["metrics"], {})
        self.assertTrue(any("PAIR" in code or "PAGE" in code for code in self.codes(result)), result)

    def test_blank_rasters_do_not_claim_successful_structure_verification(self):
        source, generated = self.root / "blank-source.png", self.root / "blank-translated.png"
        for path in (source, generated):
            with Image.new("RGB", (600, 900), "white") as image:
                image.save(path)
        result = self.compare(source, generated)
        self.assertEqual(result["source_aware"]["status"], "REVIEW_REQUIRED")


    def test_equal_layout_at_twice_resolution_does_not_create_structure_drift(self):
        source = self.page()
        generated = self.root / "twice.png"
        with Image.open(source) as image:
            image.resize((1200, 1800), Image.Resampling.NEAREST).save(generated)
        result = self.compare(source, generated, metadata={"page_number": 9})
        structural = {"SOURCE_ASPECT_DRIFT", "SOURCE_MARGIN_DRIFT", "SOURCE_CONTENT_POSITION",
                      "SOURCE_CONTENT_WIDTH", "SOURCE_HEADER_POSITION", "SOURCE_FOOTER_POSITION",
                      "SOURCE_GEOMETRY_POSITION", "SOURCE_GEOMETRY_SIZE", "SOURCE_GEOMETRY_MISSING"}
        self.assertFalse(structural & self.codes(result), result)

    def test_header_shift_is_reported_separately_from_canvas(self):
        result = self.compare(self.page(), self.page("shifted.png", header_y=110),
                              metadata={"page_number": 9})
        self.assertIn("SOURCE_HEADER_POSITION", self.codes(result))
        self.assertNotIn("SOURCE_ASPECT_DRIFT", self.codes(result))

    def test_source_relative_abnormal_margins_warn(self):
        result = self.compare(self.page(), self.page("narrow.png", left=160, right=440))
        self.assertTrue({"SOURCE_MARGIN_DRIFT", "SOURCE_CONTENT_WIDTH"} & self.codes(result), result)

    def test_sparse_source_whitespace_is_not_a_layout_defect(self):
        result = self.compare(self.page(sparse=True), self.page("sparse-vn.png", sparse=True))
        self.assertNotIn("SOURCE_WHITESPACE_DRIFT", self.codes(result))
        self.assertNotIn("SOURCE_DENSITY_DRIFT", self.codes(result))
        self.assertNotEqual(result["source_aware"]["status"], "NEEDS_RELAYOUT")

    def test_disappearing_large_triangle_is_a_missing_region_risk(self):
        result = self.compare(self.page(), self.page("no-triangle.png", geometry=False))
        self.assertIn("SOURCE_GEOMETRY_MISSING", self.codes(result))
        self.assertIn(result["source_aware"]["status"], {"WARNING", "REVIEW_REQUIRED", "NEEDS_RELAYOUT"})
        self.assertNotEqual(result["source_aware"]["status"], "PASS")

    def test_edge_touching_geometry_is_reported_without_proving_math_error(self):
        result = self.compare(self.page(), self.page("cut-risk.png", edge_geometry=True))
        self.assertIn("EDGE_CONTENT", self.codes(result))
        self.assertTrue(result["limitations"])

    def test_mirrored_even_page_accepts_odd_approved_sample(self):
        sample = self.page("odd-sample.png")
        source = self.page("even-source.png", header_side="left", footer_side="left")
        generated = self.page("even-vn.png", header_side="left", footer_side="left")
        result = self.compare(source, generated,
                              profile=replace(self.profile, approved_sample=sample, sample_page_number=9),
                              metadata={"page_number": 10})
        self.assertNotIn("SOURCE_HEADER_POSITION", self.codes(result))
        self.assertNotIn("SOURCE_FOOTER_POSITION", self.codes(result))

    def test_only_trusted_text_can_report_running_header_mismatch(self):
        source, generated = self.page(), self.page("vn.png")
        profile = replace(self.profile, canonical_header="Chương 1. Hình học phẳng")
        for trusted in (False, "true", None):
            with self.subTest(trusted=trusted):
                result = self.compare(source, generated, profile=profile,
                                      metadata={"running_header": "Chương I. Các định lý",
                                                "trusted_header_text": trusted})
                self.assertNotIn("RUNNING_HEADER_TEXT_DRIFT", self.codes(result))
        result = self.compare(source, generated, profile=profile,
                              metadata={"running_header": "Chương I. Các định lý", "trusted_header_text": True})
        self.assertIn("RUNNING_HEADER_TEXT_DRIFT", self.codes(result))

    def test_metrics_explain_value_threshold_confidence_and_reason(self):
        result = self.compare(self.page(), self.page("shifted.png", header_y=110))
        metrics = result["source_aware"]["metrics"]
        self.assertTrue(metrics)
        for metric in metrics:
            with self.subTest(metric=metric.get("name")):
                self.assertTrue({"name", "value", "threshold", "deviation", "confidence",
                                 "status", "reason"}.issubset(metric), metric)
                self.assertGreaterEqual(metric["confidence"], 0)
                self.assertLessEqual(metric["confidence"], 1)
                self.assertTrue(metric["reason"])

    def test_pipeline_source_unavailable_keeps_download_and_creates_review_report(self):
        from layout_pipeline import process_page
        generated = self.page("vn.png")
        before = generated.read_bytes()
        result = process_page(self.root / "absent.png", generated, self.profile, logger=lambda _: None)
        self.assertEqual(result["processing_status"], "COMPLETED", result)
        self.assertEqual(result["qc"]["source_aware"]["status"], "REVIEW_REQUIRED")
        self.assertEqual(before, generated.read_bytes())
        self.assertTrue((Path(result["run_dir"]) / "report.json").is_file())

    def test_pipeline_produces_inspectable_artifacts_without_modifying_inputs(self):
        from layout_pipeline import process_page
        source, generated = self.page(), self.page("vn.png", header_y=110)
        before = source.read_bytes(), generated.read_bytes()
        result = process_page(source, generated, self.profile, metadata={"page_number": 9},
                              logger=lambda _: None)
        self.assertEqual(result["processing_status"], "COMPLETED", result)
        for name in ("source_copy", "original_copy", "comparison", "evidence_overlay"):
            self.assertTrue(Path(result[name]).is_file(), name)
        self.assertEqual(Path(result["source_copy"]).read_bytes(), before[0])
        self.assertEqual(Path(result["original_copy"]).read_bytes(), before[1])
        self.assertEqual(before, (source.read_bytes(), generated.read_bytes()))
        directory = Path(result["run_dir"])
        self.assertTrue((directory / "report.json").is_file())
        self.assertTrue((directory / "report.csv").is_file())
        with Image.open(result["comparison"]) as image:
            self.assertGreater(image.width, image.height)


    def test_added_blank_canvas_changes_aspect_without_moving_geometry_in_content(self):
        source = self.page()
        generated = self.root / "padded.png"
        with Image.open(source) as original, Image.new("RGB", (750, 900), "white") as canvas:
            canvas.paste(original, (75, 0))
            canvas.save(generated)
        result = self.compare(source, generated)
        self.assertIn("SOURCE_ASPECT_DRIFT", self.codes(result))
        self.assertNotIn("SOURCE_GEOMETRY_POSITION", self.codes(result))
        self.assertNotIn("SOURCE_GEOMETRY_STRUCTURE", self.codes(result))
        self.assertNotIn("SOURCE_GEOMETRY_MISSING", self.codes(result))

    def test_missing_optional_cv_dependency_returns_review(self):
        source, generated = self.page(), self.page("vn.png")
        with patch("layout_qc._source_dependencies", side_effect=ImportError("opencv unavailable")):
            result = self.compare(source, generated)
        self.assertEqual(result["source_aware"]["status"], "REVIEW_REQUIRED")
        self.assertNotEqual(result["status"], "FAIL")
        self.assertTrue(result["findings"])

    def test_cli_directory_and_manifest_modes_create_summaries_offline(self):
        from layout_pipeline import main
        source = self.page("source/page9.png")
        generated = self.page("generated/page9VN.png")
        config = self.root / "profile.json"
        config.write_text(json.dumps({
            "enabled": True, "source_aware_enabled": False, "target_size": [600, 900],
            "margins": [35, 30, 35, 35], "normalize_enabled": False,
        }), encoding="utf-8")
        manifest = self.root / "pages.json"
        manifest.write_text(json.dumps({"version": 1, "pages": [{
            "page": 9, "source": "source/page9.png", "generated": "generated/page9VN.png",
        }]}), encoding="utf-8")
        originals = source.read_bytes(), generated.read_bytes(), config.read_bytes(), manifest.read_bytes()
        modes = [
            ["--pair-by-page", "--source-dir", str(source.parent), "--generated-dir", str(generated.parent)],
            ["--manifest", str(manifest)],
        ]
        for index, flags in enumerate(modes):
            with self.subTest(mode=flags[0]):
                output = self.root / f"cli-{index}"
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = main(["--profile", str(config), "--source-aware", "--qc-only",
                                 "--output-dir", str(output), *flags])
                self.assertIn(code, (0, 1))
                summaries = list(output.glob("batch-*/summary.json"))
                self.assertEqual(len(summaries), 1)
                summary = json.loads(summaries[0].read_text(encoding="utf-8"))
                self.assertEqual(len(summary["pages"]), 1)
                self.assertEqual(summary["pages"][0]["metadata"]["page_number"], 9)
                self.assertIn("source_aware", summary["pages"][0]["qc"])
                self.assertTrue(summaries[0].with_name("summary.csv").is_file())
        self.assertEqual(originals, (source.read_bytes(), generated.read_bytes(),
                                     config.read_bytes(), manifest.read_bytes()))

    def test_cli_single_pair_page_mismatch_is_not_silently_compared(self):
        from layout_pipeline import main
        source = self.page("source/page9.png")
        generated = self.page("generated/page10VN.png")
        config = self.root / "profile.json"
        config.write_text(json.dumps({"enabled": True, "source_aware_enabled": True,
                                     "normalize_enabled": False,
                                     "output_dir": str(self.profile.output_dir)}), encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["--profile", str(config), "--source", str(source),
                         "--generated", str(generated), "--qc-only"])
        self.assertNotEqual(code, 0)
        reports = list(self.profile.output_dir.glob("page-*/report.json"))
        if reports:
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertIn("PAIRING_MISMATCH", self.codes(report["qc"]))
            self.assertEqual(report["qc"]["source_aware"]["status"], "FAIL")


    def test_isolated_title_vertical_shift_is_detected(self):
        paths = []
        for name, y in (("title-source.png", 190), ("title-vn.png", 270)):
            path = self.page(name, sparse=True)
            with Image.open(path) as source:
                image = source.copy()
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 100, 599, 330), fill="white")
            for x in range(180, 420, 16):
                draw.rectangle((x, y, x + 10, y + 22), fill="black")
            for yy in (390, 420, 450):
                for x in range(55, 535, 12):
                    draw.rectangle((x, yy, x + 6, yy + 9), fill="black")
            image.save(path)
            image.close()
            paths.append(path)
        result = self.compare(*paths)
        self.assertIn("SOURCE_TITLE_POSITION", self.codes(result))

    def test_scan_border_is_measurement_only_and_does_not_shift_body(self):
        from PIL import ImageOps
        source = self.page()
        scanned = self.root / "scan.png"
        with Image.open(source) as image:
            ImageOps.expand(image, border=8, fill="black").save(scanned)
        before = scanned.read_bytes()
        result = self.compare(scanned, source)
        self.assertTrue(result["metrics"]["source"]["scan_border_removed_for_measurement"])
        self.assertNotIn("SOURCE_GEOMETRY_POSITION", self.codes(result))
        self.assertNotIn("SOURCE_MARGIN_DRIFT", self.codes(result))
        self.assertEqual(before, scanned.read_bytes())

    def test_slight_scan_skew_keeps_original_and_uses_tolerance(self):
        source = self.page()
        skewed = self.root / "skewed.png"
        with Image.open(source) as image:
            image.rotate(1, fillcolor="white").save(skewed)
        before = skewed.read_bytes()
        result = self.compare(skewed, source)
        self.assertGreater(result["metrics"]["source"]["skew_tolerance"], 0)
        self.assertNotEqual(result["status"], "FAIL")
        self.assertEqual(before, skewed.read_bytes())

    def test_formula_like_text_touching_edge_is_a_clipping_risk(self):
        source = self.page()
        generated = self.page("formula-edge.png")
        with Image.open(generated) as raw:
            image = raw.copy()
        draw = ImageDraw.Draw(image)
        draw.line((0, 700, 80, 700), fill="black", width=3)
        draw.text((0, 680), "A+B=1", fill="black")
        image.save(generated)
        image.close()
        result = self.compare(source, generated)
        self.assertIn("EDGE_CONTENT", self.codes(result))
        self.assertEqual(result["source_aware"]["formula_verification"], "REVIEW_REQUIRED")

    def test_centered_footer_template_is_supported(self):
        source = self.page("centered.png")
        with Image.open(source) as raw:
            image = raw.copy()
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 830, 599, 899), fill="white")
        draw.rectangle((295, 850, 304, 863), fill="black")
        image.save(source)
        image.close()
        result = self.compare(source, source, profile=replace(self.profile, footer_alignment="center"),
                              metadata={"page_number": 10})
        self.assertNotIn("FOOTER_ALIGNMENT", self.codes(result))

    def test_visual_typography_reference_warns_without_claiming_font_size(self):
        from layout_qc import measure_source_page
        source = self.page()
        reference = dict(measure_source_page(source, self.profile)["typography"])
        reference["glyph_height"] *= .5
        result = self.compare(source, source, metadata={"typography_reference": reference})
        self.assertIn("TYPOGRAPHY_GLYPH_HEIGHT", self.codes(result))
        self.assertEqual(result["metrics"]["generated"]["typography"]["kind"], "visual_proxy_not_font_size")

    def test_mixed_footer_text_does_not_move_connected_footer_ornament(self):
        source = self.page("footer-source.png")
        generated = self.page("footer-vn.png")
        for path in (source, generated):
            with Image.open(path) as raw:
                image = raw.copy()
            ImageDraw.Draw(image).line((400, 880, 550, 880), fill="black", width=3)
            if path == generated:
                ImageDraw.Draw(image).text((60, 840), "A+B=C body formula", fill="black")
            image.save(path)
            image.close()
        result = self.compare(source, generated)
        self.assertNotIn("SOURCE_FOOTER_POSITION", self.codes(result))


    def test_large_canvas_padding_does_not_claim_internal_relayout(self):
        source = self.page()
        generated = self.root / "padded.png"
        with Image.open(source) as raw, Image.new("RGB", (1000, 1200), "white") as padded:
            padded.paste(raw, (200, 150))
            padded.save(generated)
        result = self.compare(source, generated)
        self.assertTrue(result["source_aware"]["identical_ink_with_canvas_changes"])
        self.assertIn("SOURCE_ASPECT_DRIFT", self.codes(result))
        self.assertFalse({"SOURCE_GEOMETRY_POSITION", "SOURCE_GEOMETRY_SIZE", "SOURCE_CONTENT_POSITION",
                          "SOURCE_MARGIN_DRIFT", "SOURCE_HEADER_POSITION"} & self.codes(result))


    def test_none_source_path_returns_review_in_direct_api(self):
        result = self.compare(None, self.page())
        self.assertIn("SOURCE_UNAVAILABLE", self.codes(result))
        self.assertEqual(result["source_aware"]["status"], "REVIEW_REQUIRED")


class SourcePairingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_dir, self.generated_dir = self.root / "source", self.root / "generated"
        self.source_dir.mkdir()
        self.generated_dir.mkdir()

    def touch(self, directory, name):
        path = directory / name
        path.write_bytes(b"filename pairing fixture, deliberately not decoded")
        return path

    def test_directory_pairs_sort_by_page_and_not_lexicographic_name(self):
        from layout_pipeline import collect_directory_pairs
        for page in (13, 9, 10, 11, 12):
            self.touch(self.source_dir, f"page-{page}.png")
            self.touch(self.generated_dir, f"page-{page}VN.png")
        pairs = collect_directory_pairs(self.source_dir, self.generated_dir)
        self.assertEqual([pair["metadata"]["page_number"] for pair in pairs], [9, 10, 11, 12, 13])
        for pair in pairs:
            self.assertEqual(Path(pair["source"]).stem, f'page-{pair["metadata"]["page_number"]}')
            self.assertEqual(Path(pair["generated"]).stem, f'page-{pair["metadata"]["page_number"]}VN')

    def test_directory_duplicate_page_numbers_are_rejected(self):
        from layout_pipeline import collect_directory_pairs
        self.touch(self.source_dir, "9.png")
        self.touch(self.source_dir, "page9.png")
        self.touch(self.generated_dir, "9VN.png")
        with self.assertRaises(ValueError):
            collect_directory_pairs(self.source_dir, self.generated_dir)

    def test_directory_ambiguous_numeric_groups_require_manifest(self):
        from layout_pipeline import collect_directory_pairs
        self.touch(self.source_dir, "1_9.png")
        self.touch(self.generated_dir, "1_9VN.png")
        with self.assertRaises(ValueError):
            collect_directory_pairs(self.source_dir, self.generated_dir)

    def test_unmatched_page_never_reuses_a_different_source(self):
        from layout_pipeline import collect_directory_pairs
        other = self.touch(self.source_dir, "9.png")
        generated = self.touch(self.generated_dir, "10VN.png")
        pairs = collect_directory_pairs(self.source_dir, self.generated_dir)
        self.assertEqual(len(pairs), 2)
        orphan = next(pair for pair in pairs if pair["metadata"]["page_number"] == 10)
        self.assertEqual(Path(orphan["generated"]), generated)
        self.assertIsNone(orphan["source"])
        source_only = next(pair for pair in pairs if pair["metadata"]["page_number"] == 9)
        self.assertEqual(source_only["source"], other)
        self.assertIsNone(source_only["generated"])

    def manifest(self, pages):
        path = self.root / "pairs.json"
        path.write_text(json.dumps({"version": 1, "pages": pages}), encoding="utf-8")
        return path

    def test_manifest_page_mapping_overrides_storage_filename_numbers(self):
        from layout_pipeline import load_manifest
        source = self.touch(self.source_dir, "23.png")
        generated = self.touch(self.generated_dir, "00023VN.png")
        pairs = load_manifest(self.manifest([{
            "page": 9, "source": "source/23.png", "generated": "generated/00023VN.png",
            "trusted_header_text": True, "running_header": "Chương 1. Hình học phẳng",
        }]))
        self.assertEqual(len(pairs), 1)
        pair = pairs[0]
        self.assertEqual(Path(pair["source"]), source)
        self.assertEqual(Path(pair["generated"]), generated)
        self.assertEqual(pair["metadata"]["page_number"], 9)

    def test_manifest_rejects_explicit_source_translation_page_mismatch(self):
        from layout_pipeline import load_manifest
        with self.assertRaises(ValueError):
            load_manifest(self.manifest([{
                "page": 9, "source": "source/23.png", "generated": "generated/00024VN.png",
                "source_page_number": 9, "generated_page_number": 10,
            }]))

    def test_manifest_duplicate_logical_page_is_rejected(self):
        from layout_pipeline import load_manifest
        entry = {"page": 9, "source": "source/23.png", "generated": "generated/00023VN.png"}
        with self.assertRaises(ValueError):
            load_manifest(self.manifest([entry, entry]))

    def test_manifest_never_trusts_truthy_string_as_transcription(self):
        from layout_pipeline import load_manifest
        with self.assertRaises(ValueError):
            load_manifest(self.manifest([{
                "page": 9, "source": "source/23.png", "generated": "generated/00023VN.png",
                "running_header": "Chương 1", "trusted_header_text": "true",
            }]))


if __name__ == "__main__":
    unittest.main()
