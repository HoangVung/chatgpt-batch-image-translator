"""Synthetic raster tests: normalization preserves every decoded source pixel."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from layout_normalizer import normalize_image
from layout_profile import LayoutProfile


class LayoutNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.profile = LayoutProfile(target_size=(120, 160), margins=(10, 10, 10, 10))

    def source(self, name="page.png", mode="RGB", size=(100, 140), box=(20, 25, 80, 115), **save):
        image = Image.new(mode, size, (255, 255, 255, 255) if mode == "RGBA" else "white")
        if box:
            ImageDraw.Draw(image).rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill="black")
        path = self.directory / name
        image.save(path, **save)
        image.close()
        return path

    def run_normalizer(self, path, profile=None, qc_result=None):
        report, output = normalize_image(path, profile or self.profile, qc_result)
        if output is not None:
            self.addCleanup(output.close)
        return report, output

    def assert_preserved(self, source, report, output):
        with Image.open(source) as original:
            x, y = report["offset"]
            pasted = output.crop((x, y, x + original.width, y + original.height))
            self.addCleanup(pasted.close)
            self.assertEqual(pasted.mode, original.mode)
            self.assertEqual(pasted.tobytes(), original.tobytes())

    def test_padding_centers_content_and_preserves_all_rgb_pixels(self):
        source = self.source()
        report, output = self.run_normalizer(source)
        self.assertEqual(report["status"], "NORMALIZED")
        self.assertEqual(report["offset"], [10, 10])
        self.assertEqual(report["content_bbox"], [20, 25, 80, 115])
        self.assertEqual(report["target_content_bbox"], [30, 35, 90, 125])
        self.assertEqual(output.size, (120, 160))
        self.assertEqual(output.getpixel((0, 0)), (255, 255, 255))
        self.assert_preserved(source, report, output)

    def test_offset_clamped_to_keep_entire_raster_on_canvas(self):
        source = self.source(box=(12, 20, 45, 110))
        report, output = self.run_normalizer(source)
        self.assertEqual(report["status"], "NORMALIZED")
        self.assertEqual(report["offset"][0], 20)
        self.assert_preserved(source, report, output)

    def test_same_size_is_unchanged_exact_pixel_copy(self):
        source = self.source(size=(120, 160), box=(15, 20, 105, 140))
        report, output = self.run_normalizer(source)
        self.assertEqual(report["status"], "UNCHANGED")
        self.assertEqual(report["offset"], [0, 0])
        self.assert_preserved(source, report, output)

    def test_rgba_copies_alpha_and_invisible_rgb_without_compositing(self):
        source = self.source(mode="RGBA")
        with Image.open(source) as loaded:
            original = loaded.copy()
        original.putpixel((0, 0), (10, 20, 30, 0))
        original.putpixel((22, 26), (200, 70, 30, 97))
        original.save(source)
        original.close()
        report, output = self.run_normalizer(source)
        self.assertEqual(report["status"], "NORMALIZED")
        self.assertEqual(output.getpixel((0, 0)), (255, 255, 255, 255))
        self.assert_preserved(source, report, output)

    def test_too_small_canvas_does_not_resize_or_crop(self):
        source = self.source(size=(121, 140))
        report, output = self.run_normalizer(source)
        self.assertEqual(report["status"], "NEEDS_RELAYOUT")
        self.assertIn("source_raster_exceeds_target_canvas", report["reasons"])
        self.assertIsNone(output)

    def test_impossible_margins_do_not_erase_ink(self):
        source = self.source(size=(120, 160), box=(1, 5, 119, 155))
        report, output = self.run_normalizer(source)
        self.assertEqual(report["status"], "NEEDS_RELAYOUT")
        self.assertIn("content_cannot_fit_without_editing_source", report["reasons"])
        self.assertIsNone(output)

    def test_qc_requires_relayout_prevents_derivative(self):
        source = self.source()
        qc = {"findings": [{"code": "title_band_deviation", "requires_relayout": True}]}
        report, output = self.run_normalizer(source, qc_result=qc)
        self.assertEqual(report["status"], "NEEDS_RELAYOUT")
        self.assertEqual(report["reasons"], ["qc_requires_relayout:title_band_deviation"])
        self.assertIsNone(output)

    def test_invalid_source_sample_or_generated_qc_blocks_output(self):
        source = self.source()
        for code in ("INVALID_SOURCE", "INVALID_SAMPLE", "INVALID_GENERATED"):
            with self.subTest(code=code):
                qc = {"findings": [{"code": code, "requires_relayout": False}]}
                report, output = self.run_normalizer(source, qc_result=qc)
                self.assertEqual(report["status"], "ERROR")
                self.assertEqual(report["reasons"], ["qc_invalid_input:" + code])
                self.assertIsNone(output)

    def test_safe_qc_warning_can_be_normalized(self):
        source = self.source()
        qc = {"findings": [{"code": "dimensions", "requires_relayout": False}]}
        report, output = self.run_normalizer(source, qc_result=qc)
        self.assertEqual(report["status"], "NORMALIZED")
        self.assert_preserved(source, report, output)

    def test_page_number_template_requires_semantic_review(self):
        profile = LayoutProfile(target_size=(120, 160), margins=(10, 10, 10, 20),
                                page_number_region=(50, 145, 70, 158))
        report, output = self.run_normalizer(self.source(), profile)
        self.assertEqual(report["status"], "NEEDS_RELAYOUT")
        self.assertEqual(report["reasons"], ["page_number_template_requires_review"])
        self.assertIsNone(output)

    def test_blank_page_requires_review(self):
        report, output = self.run_normalizer(self.source(box=None))
        self.assertEqual(report["status"], "NEEDS_RELAYOUT")
        self.assertIsNone(output)

    def test_corrupt_or_missing_input_returns_error(self):
        corrupt = self.directory / "corrupt.png"
        corrupt.write_bytes(b"not an image")
        for path in (corrupt, self.directory / "missing.png"):
            with self.subTest(path=path):
                report, output = self.run_normalizer(path)
                self.assertEqual(report["status"], "ERROR")
                self.assertTrue(report["error"])
                self.assertIsNone(output)

    def test_nonidentity_exif_requires_review(self):
        exif = Image.Exif()
        exif[274] = 6
        report, output = self.run_normalizer(self.source(exif=exif))
        self.assertEqual(report["status"], "NEEDS_RELAYOUT")
        self.assertEqual(report["reasons"], ["exif_orientation_requires_review"])
        self.assertIsNone(output)

    def test_multiple_frames_require_review(self):
        frame = Image.new("RGB", (100, 140), "white")
        path = self.source(name="frames.tiff", save_all=True, append_images=[frame])
        frame.close()
        report, output = self.run_normalizer(path)
        self.assertEqual(report["status"], "NEEDS_RELAYOUT")
        self.assertEqual(report["reasons"], ["multiple_frames_require_review"])
        self.assertIsNone(output)

    def test_palette_and_color_key_require_review(self):
        palette = self.source()
        with Image.open(palette) as loaded:
            converted = loaded.convert("P")
        converted.save(palette)
        converted.close()
        color_key = self.source(name="key.png", transparency=(255, 255, 255))
        for path in (palette, color_key):
            with self.subTest(path=path):
                report, output = self.run_normalizer(path)
                self.assertEqual(report["status"], "NEEDS_RELAYOUT")
                self.assertIsNone(output)

    def test_pixel_limit_blocks_source_before_normalization(self):
        profile = LayoutProfile(target_size=(60, 80), margins=(5, 5, 5, 5), max_pixels=4800)
        report, output = self.run_normalizer(self.source(), profile)
        self.assertEqual(report["status"], "ERROR")
        self.assertIn("max_pixels", report["error"])
        self.assertIsNone(output)

    def test_icc_and_dpi_preserved_on_derivative(self):
        source = self.source(icc_profile=b"synthetic ICC profile", dpi=(144, 144))
        report, output = self.run_normalizer(source)
        self.assertEqual(report["status"], "NORMALIZED")
        with Image.open(source) as original:
            self.assertEqual(output.info["icc_profile"], original.info["icc_profile"])
            self.assertEqual(output.info["dpi"], original.info["dpi"])

    def test_repeated_calls_do_not_write_or_change_source_hash(self):
        source = self.source()
        before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        before_files = set(self.directory.iterdir())
        for _ in range(3):
            report, output = self.run_normalizer(source)
            self.assertEqual(report["status"], "NORMALIZED")
            self.assert_preserved(source, report, output)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before_hash)
        self.assertEqual(set(self.directory.iterdir()), before_files)


if __name__ == "__main__":
    unittest.main()