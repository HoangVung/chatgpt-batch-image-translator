import csv
from pathlib import Path


FAILED_STATUSES = frozenset({"fail", "failed", "manual", "error"})


def read_latest_progress(progress_file):
    """Return the last recorded row for each source file in a progress CSV."""
    latest = {}
    progress_path = Path(progress_file)

    if not progress_path.exists():
        return latest

    with progress_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            file_name = (row.get("file") or "").strip()
            if file_name:
                latest[file_name] = row

    return latest


def latest_failed_rows(progress_file):
    """Return only files whose most recent progress row is a failure."""
    return [
        row
        for row in read_latest_progress(progress_file).values()
        if (row.get("status") or "").strip().lower() in FAILED_STATUSES
    ]
