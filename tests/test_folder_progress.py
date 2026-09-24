import tempfile
import unittest
from pathlib import Path

from PIL import Image

from desktop.folder_progress import FolderProgress


class FolderProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.output = self.root / "output"
        self.source.mkdir()
        self.output.mkdir()
        self.settings = dict(image_folder=str(self.source), download_folder=str(self.output),
                             start_from="3_3.jpg", batch_size="1")
        self.counter = FolderProgress()

    def image(self, name):
        Image.new("RGB", (100, 100)).save(self.output / name)

    def test_counts_entire_folder_valid_outputs_and_rechecks_changed_files(self):
        for name in ("1_1.jpg", "2_2.PNG", "3_3.webp", "4_4.jpeg", "notes.txt"):
            (self.source / name).touch()
        (self.source / "nested").mkdir()
        (self.source / "nested" / "5_5.jpg").touch()
        self.image("00001_00001VN.png")
        self.image("99999_99999VN.png")  # Unrelated output is not a source image.
        (self.output / "00002_00002VN.png").write_text("broken")
        (self.output / "progress.csv").write_text("file,status\n1_1.jpg,done\n1_1.jpg,done\n2_2.PNG,done\n3_3.webp,done\n")
        self.assertEqual(self.counter.read(self.settings), {"done": 1, "total": 4})
        self.image("00002_00002VN.png")
        self.assertEqual(self.counter.read(self.settings), {"done": 2, "total": 4})
        (self.output / "00001_00001VN.png").unlink()
        self.assertEqual(self.counter.read(self.settings), {"done": 1, "total": 4})

    def test_legacy_outputs_require_latest_done_and_unambiguous_page(self):
        for name in ("1_1.jpg", "1_2.jpg", "2_3.jpg", "3_4.jpg"):
            (self.source / name).touch()
        for name in ("00001VN.png", "00002VN.png", "00003VN.png"):
            self.image(name)
        (self.output / "progress.csv").write_text("file,status\n1_1.jpg,done\n1_2.jpg,done\n2_3.jpg,done\n3_4.jpg,done\n3_4.jpg,fail\n")
        self.assertEqual(self.counter.read(self.settings), {"done": 1, "total": 4})

    def test_unconfigured_missing_and_separate_output(self):
        self.assertEqual(self.counter.read({}), {"done": 0, "total": 0})
        (self.source / "1_1.jpg").touch()
        self.image("00001_00001VN.png")
        self.assertEqual(self.counter.read(self.settings), {"done": 1, "total": 1})
        self.settings["download_folder"] = str(self.root / "other-output")
        self.assertEqual(self.counter.read(self.settings), {"done": 0, "total": 1})
        self.assertFalse((self.root / "other-output").exists())
        self.settings["image_folder"] = str(self.root / "missing")
        self.assertEqual(self.counter.read(self.settings), {"done": None, "total": None})


if __name__ == "__main__":
    unittest.main()
