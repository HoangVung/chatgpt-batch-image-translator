"""Small synthetic raster fixtures: no provider access or translation quota."""
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw

from layout_profile import LayoutProfile, load_profile
from layout_qc import check_layout, measure_image


class LayoutQcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.profile = LayoutProfile(target_size=(200, 300), margins=(20, 30, 20, 30))
        self.source = self.page("source.png")

    def page(self, name, size=(200, 300), left=20, right=180, rows=None):
        path = self.root / name
        with Image.new("RGB", size, "white") as image:
            draw = ImageDraw.Draw(image)
            for y in (range(30, 270, 20) if rows is None else rows):
                draw.rectangle((left, y, right - 1, min(y + 9, size[1] - 1)), fill="black")
            draw.rectangle((left, 260, right - 1, 269), fill="black")
            image.save(path)
        return path

    def result(self, path, profile=None):
        return check_layout(self.source, path, profile or self.profile)

    def codes(self, result):
        return {item["code"] for item in result["findings"]}

    def test_same_layout_passes_and_preserves_originals(self):
        generated = self.page("generated.png")
        before = [hashlib.sha256(p.read_bytes()).digest() for p in (self.source, generated)]
        result = self.result(generated)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["metrics"]["generated"]["content_bbox"], [20, 30, 180, 270])
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).digest() for p in (self.source, generated)])
        self.assertIn("does not validate translation", result["limitations"][0])
        json.dumps(result)

    def test_different_target_dimensions_warn_without_aspect_drift(self):
        generated = self.root / "larger.png"
        with Image.open(self.source) as image:
            image.resize((400, 600), Image.Resampling.NEAREST).save(generated)
        result = self.result(generated)
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("TARGET_SIZE_DRIFT", self.codes(result))
        self.assertNotIn("TARGET_ASPECT_DRIFT", self.codes(result))
        self.assertNotIn("SOURCE_SIZE_DRIFT", self.codes(result))
        self.assertNotIn("SOURCE_ASPECT_DRIFT", self.codes(result))

    def test_source_dimensions_aspect_and_density_are_informational(self):
        source = self.page("different-source.png", size=(400, 400))
        generated = self.page("target-matching.png")
        result = check_layout(source, generated, self.profile)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["findings"], [])
        comparison = result["metrics"]["source_comparison"]
        self.assertAlmostEqual(comparison["dimension_difference"], 0.5)
        self.assertAlmostEqual(comparison["aspect_difference"], 1 / 3)
        self.assertGreater(comparison["ink_fraction_difference"],
                           self.profile.thresholds["ink_difference_warning"])
        self.assertIs(comparison["affects_status"], False)

    def test_longer_translated_text_does_not_trigger_source_density_warning(self):
        source = self.page("short-source.png", rows=[30, 50])
        generated = self.page("longer-translation.png")
        result = check_layout(source, generated, self.profile)
        density_difference = (result["metrics"]["generated"]["ink_fraction"] -
                              result["metrics"]["source"]["ink_fraction"])
        self.assertGreater(density_difference,
                           self.profile.thresholds["ink_difference_warning"])
        self.assertNotIn("INK_DENSITY_DRIFT", self.codes(result))
        self.assertEqual(result["status"], "PASS", result)

    def test_aspect_violation_fails(self):
        result = self.result(self.page("wide.png", size=(300, 300)))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("TARGET_ASPECT_DRIFT", self.codes(result))

    def test_margin_encroachment_warns(self):
        result = self.result(self.page("encroaching.png", left=5, right=180))
        self.assertIn("TARGET_MARGIN_DRIFT", self.codes(result))

    def test_extra_bottom_whitespace_is_not_margin_encroachment(self):
        generated = self.root / "short-page.png"
        with Image.new("RGB", (200, 300), "white") as image:
            draw = ImageDraw.Draw(image)
            for y in (30, 50, 70):
                draw.rectangle((20, y, 179, y + 9), fill="black")
            image.save(generated)
        result = self.result(generated)
        self.assertGreater(result["metrics"]["generated"]["normalized_margins"][3], 0.7)
        self.assertNotIn("TARGET_MARGIN_DRIFT", self.codes(result))
        self.assertEqual(result["status"], "PASS", result)

    def test_horizontal_imbalance_warns_even_inside_safe_margins(self):
        result = self.result(self.page("unbalanced.png", left=45, right=175))
        self.assertIn("HORIZONTAL_IMBALANCE", self.codes(result))
        self.assertNotIn("TARGET_MARGIN_DRIFT", self.codes(result))
        self.assertEqual(result["status"], "WARNING", result)

    def test_asymmetric_content_region_controls_horizontal_balance(self):
        profile = replace(self.profile, margins=(40, 30, 20, 30),
                          content_region=(50, 30, 180, 270))
        for name, left, should_warn in (("centered.png", 75, False),
                                        ("shifted.png", 60, True)):
            with self.subTest(name=name):
                generated = self.root / name
                with Image.new("RGB", (200, 300), "white") as image:
                    ImageDraw.Draw(image).rectangle((left, 30, left + 79, 269),
                                                    fill="black")
                    image.save(generated)
                result = self.result(generated, profile)
                self.assertEqual("HORIZONTAL_IMBALANCE" in self.codes(result),
                                 should_warn, result)
                self.assertNotIn("TARGET_MARGIN_DRIFT", self.codes(result))

    def test_short_page_without_footer_accepts_dense_sample_bottom_whitespace(self):
        generated = self.root / "short-no-footer.png"
        with Image.new("RGB", (200, 300), "white") as image:
            draw = ImageDraw.Draw(image)
            for y in (30, 50, 70):
                draw.rectangle((20, y, 179, y + 9), fill="black")
            image.save(generated)
        profile = replace(self.profile, approved_sample=self.source)
        result = check_layout(generated, generated, profile)
        actual = result["metrics"]["generated"]["normalized_margins"]
        reference = result["metrics"]["sample"]["normalized_margins"]
        self.assertGreater(actual[3] - reference[3],
                           profile.thresholds["sample_margin_warning"])
        self.assertNotIn("SAMPLE_MARGIN_DRIFT", self.codes(result))
        self.assertNotIn("TARGET_MARGIN_DRIFT", self.codes(result))
        self.assertIn("INK_DENSITY_DRIFT", self.codes(result))

    def test_opposite_mirrored_sample_margins_are_accepted(self):
        sample = self.page("even-page.png", left=26, right=186)
        generated = self.page("odd-page.png", left=14, right=174)
        result = self.result(generated, replace(self.profile, approved_sample=sample))
        actual = result["metrics"]["generated"]["normalized_margins"]
        reference = result["metrics"]["sample"]["normalized_margins"]
        self.assertGreater(abs(actual[0] - reference[0]),
                           self.profile.thresholds["sample_margin_warning"])
        self.assertNotIn("SAMPLE_MARGIN_DRIFT", self.codes(result))
        self.assertEqual(result["status"], "PASS", result)

    def test_sample_margin_drift_still_warns_when_neither_orientation_matches(self):
        sample = self.page("sample.png", left=26, right=186)
        generated = self.page("narrow-shifted.png", left=42, right=186)
        result = self.result(generated, replace(self.profile, approved_sample=sample))
        self.assertIn("SAMPLE_MARGIN_DRIFT", self.codes(result))

    def test_unusual_interior_whitespace_warns(self):
        result = self.result(self.page("gap.png", rows=[30, 50, 230, 250]))
        self.assertIn("INTERIOR_WHITESPACE", self.codes(result))

    def test_same_large_gap_is_not_an_anomaly(self):
        gap = self.page("gap.png", rows=[30, 50, 230, 250])
        result = check_layout(gap, gap, self.profile)
        self.assertNotIn("INTERIOR_WHITESPACE", self.codes(result))

    def test_source_ending_page_gap_is_preserved_with_dense_approved_sample(self):
        source = self.page("section-end-source.png", rows=[30, 50, 230, 250])
        generated = self.page("section-end-translation.png", rows=[30, 50, 230, 250])
        profile = replace(self.profile, approved_sample=self.source)
        result = check_layout(source, generated, profile)
        metrics = result["metrics"]
        gap_delta = (metrics["generated"]["bands"]["largest_interior_gap"]["fraction"] -
                     metrics["sample"]["bands"]["largest_interior_gap"]["fraction"])
        self.assertGreater(gap_delta, self.profile.thresholds["whitespace_band_warning"])
        self.assertNotIn("INTERIOR_WHITESPACE", self.codes(result))
        self.assertIn("INK_DENSITY_DRIFT", self.codes(result))

    def test_edge_content_fails_without_claiming_proven_clipping(self):
        result = self.result(self.page("edge.png", left=0))
        finding = next(f for f in result["findings"] if f["code"] == "LEFT_EDGE_CONTENT")
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(finding["requires_relayout"])
        self.assertIn("possible", finding["message"])

    def test_near_edge_warns(self):
        result = self.result(self.page("near.png", left=2))
        self.assertIn("LEFT_NEAR_EDGE", self.codes(result))
        self.assertEqual(result["status"], "WARNING")

    def test_empty_page_fails(self):
        generated = self.root / "empty.png"
        Image.new("RGB", (200, 300), "white").save(generated)
        self.assertIn("EMPTY_PAGE", self.codes(self.result(generated)))

    def test_corrupt_and_missing_images_report_fail(self):
        corrupt = self.root / "bad.png"
        corrupt.write_bytes(b"not an image")
        for path in (corrupt, self.root / "missing.png"):
            with self.subTest(path=path):
                self.assertIn("INVALID_GENERATED", self.codes(self.result(path)))
                with self.assertRaises(ValueError):
                    measure_image(path, self.profile)
        result = check_layout(corrupt, self.source, self.profile)
        self.assertIn("INVALID_SOURCE", self.codes(result))

    def test_qc_disabled_does_not_open_paths(self):
        result = check_layout("missing-source", "missing-output", replace(self.profile, qc_enabled=False))
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["metrics"], {})

    def test_oversized_image_is_rejected(self):
        generated = self.page("oversized.png", size=(400, 400))
        profile = replace(self.profile, max_pixels=60_000)
        self.assertIn("INVALID_GENERATED", self.codes(self.result(generated, profile)))

    def test_multiframe_is_rejected(self):
        path = self.root / "animation.gif"
        frames = [Image.new("RGB", (200, 300), color) for color in ("white", "black")]
        frames[0].save(path, save_all=True, append_images=frames[1:])
        self.assertIn("INVALID_GENERATED", self.codes(self.result(path)))

    def test_rotated_exif_is_rejected(self):
        path = self.root / "rotated.jpg"
        with Image.open(self.source) as image:
            exif = image.getexif()
            exif[274] = 6
            image.save(path, exif=exif)
        self.assertIn("INVALID_GENERATED", self.codes(self.result(path)))

    def test_transparency_composites_on_white(self):
        path = self.root / "transparent.png"
        Image.new("RGBA", (200, 300), (0, 0, 0, 0)).save(path)
        self.assertIsNone(measure_image(path, self.profile)["content_bbox"])

    def test_approved_sample_title_suspicion_requires_evidence(self):
        generated = self.page("title.png")
        with Image.open(generated) as image:
            ImageDraw.Draw(image).rectangle((20, 30, 179, 65), fill="black")
            image.save(generated)
        self.assertNotIn("TITLE_HEIGHT_SUSPECT", self.codes(self.result(generated)))
        profile = replace(self.profile, approved_sample=self.source)
        result = self.result(generated, profile)
        finding = next(f for f in result["findings"] if f["code"] == "TITLE_HEIGHT_SUSPECT")
        self.assertTrue(finding["requires_relayout"])
        self.assertIn("may be", finding["message"])

    def test_header_and_footer_occupancy_vs_sample(self):
        generated = self.page("header-footer.png", rows=[10, 30, 50, 70, 90, 110, 130, 150, 170, 190, 210, 230, 250, 280])
        profile = replace(self.profile, approved_sample=self.source)
        codes = self.codes(self.result(generated, profile))
        self.assertIn("HEADER_SAMPLE_DRIFT", codes)
        self.assertIn("FOOTER_SAMPLE_DRIFT", codes)

    def test_page_number_template_does_not_infer_or_move_digits(self):
        profile = replace(self.profile, page_number_region=(80, 275, 120, 295))
        generated = self.page("footer.png", rows=[30, 50, 70, 90, 110, 130, 150, 170, 190, 210, 230, 250, 280])
        finding = next(f for f in self.result(generated, profile)["findings"]
                       if f["code"] == "FOOTER_OUTSIDE_NUMBER_TEMPLATE")
        self.assertTrue(finding["requires_relayout"])

    def test_tiny_raster_template_rounding_is_safe(self):
        profile = replace(self.profile, page_number_region=(80, 275, 120, 295))
        path = self.root / "tiny.png"
        Image.new("RGB", (2, 3), "white").save(path)
        metrics = measure_image(path, profile)
        self.assertEqual(metrics["bands"]["page_number"]["occupancy"], 0)

    def test_invalid_sample_reports_fail(self):
        profile = replace(self.profile, approved_sample=self.root / "missing.png")
        self.assertIn("INVALID_SAMPLE", self.codes(self.result(self.source, profile)))


class LayoutProfileTests(unittest.TestCase):
    def test_profile_defaults_are_opt_in(self):
        self.assertFalse(LayoutProfile().enabled)

    def test_invalid_profile_values_are_rejected(self):
        cases = [dict(enabled=1), dict(target_size=(0, 3)), dict(target_size=(100, 100)),
                 dict(max_pixels=60_000_001), dict(ink_luma_threshold=255),
                 dict(content_region=(0, 0, 1601, 2400)),
                 dict(content_region=(0, 100, 1500, 2260)),
                 dict(page_number_region=(1, 1, 10, 10)), dict(output_dir=""),
                 dict(thresholds={"margin_warning": float("nan")}),
                 dict(thresholds={"edge_fail": .5}), dict(thresholds={"unknown": .1})]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                LayoutProfile(**values)

    def test_profile_resolves_relative_paths_and_rejects_bad_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps({"approved_sample": "sample.png", "output_dir": "results"}))
            profile = load_profile(path)
            self.assertEqual(profile.approved_sample, path.parent / "sample.png")
            self.assertEqual(profile.output_dir, path.parent / "results")
            for invalid in ({"output_dir": 1}, {"approved_sample": []}, {"surprise": 1}, []):
                path.write_text(json.dumps(invalid))
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    load_profile(path)


if __name__ == "__main__":
    unittest.main()
