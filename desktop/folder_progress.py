"""Read-only whole-folder counts using the worker's output reconciliation rules."""

from collections import Counter
from pathlib import Path

from PIL import Image

from progress_utils import read_latest_progress


class FolderProgress:
    def __init__(self):
        self._valid_cache = {}

    def _valid(self, path, cache):
        try:
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            previous = self._valid_cache.get(path)
            if previous and previous[0] == signature:
                cache[path] = previous
                return previous[1]
            with Image.open(path) as image:
                valid = min(image.size) >= 80
                if valid:
                    image.verify()
            cache[path] = (signature, valid)
            return valid
        except (OSError, ValueError, SyntaxError):
            return False

    def read(self, settings):
        source = str(settings.get("image_folder", "")).strip()
        output = str(settings.get("download_folder", "")).strip()
        if not source:
            self._valid_cache = {}
            return {"done": 0, "total": 0}
        try:
            images = [p for p in Path(source).iterdir()
                      if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
        except OSError:
            return {"done": None, "total": None}
        if not output:
            self._valid_cache = {}
            return {"done": 0, "total": len(images)}
        try:
            latest = read_latest_progress(Path(output) / "progress.csv")
        except (OSError, UnicodeError):
            latest = {}
        numbers = {}
        for image in images:
            parts = image.stem.split("_")
            try:
                left = int(parts[0])
            except ValueError:
                left = 999999999
            try:
                right = int(parts[1])
            except (ValueError, IndexError):
                right = 999999999
            numbers[image] = (left, right)
        pages = Counter(left for left, _ in numbers.values())
        done, cache = 0, {}
        for image, (left, right) in numbers.items():
            valid = (left != 999999999 and right != 999999999
                     and self._valid(Path(output) / f"{left:05d}_{right:05d}VN.png", cache))
            status = (latest.get(image.name, {}).get("status") or "").strip().lower()
            if not valid and status == "done" and left != 999999999 and pages[left] == 1:
                valid = self._valid(Path(output) / f"{left:05d}VN.png", cache)
            done += bool(valid)
        self._valid_cache = cache
        return {"done": done, "total": len(images)}
