import os
import shutil
from pathlib import Path
from progress_utils import latest_failed_rows

IMAGE_FOLDER = os.getenv("IMAGE_FOLDER", r"D:\images")
DOWNLOAD_FOLDER = os.getenv("DOWNLOAD_FOLDER", r"D:\images_vn")
RETRY_FOLDER = os.getenv("RETRY_FOLDER", r"D:\images_failed_retry")

PROGRESS_FILE = os.path.join(DOWNLOAD_FOLDER, "progress.csv")


def main():
    if not os.path.exists(PROGRESS_FILE):
        print(f"Không thấy progress.csv: {PROGRESS_FILE}")
        return

    os.makedirs(RETRY_FOLDER, exist_ok=True)

    failed_files = sorted(
        (row.get("file") or "").strip()
        for row in latest_failed_rows(PROGRESS_FILE)
        if (row.get("file") or "").strip()
    )

    if not failed_files:
        print("Không có ảnh lỗi để copy.")
        return

    copied = 0
    missing = []

    for file_name in failed_files:
        src = Path(IMAGE_FOLDER) / file_name
        dst = Path(RETRY_FOLDER) / file_name

        if src.exists():
            shutil.copy2(src, dst)
            copied += 1
        else:
            missing.append(file_name)

    print(f"Đã copy {copied} ảnh lỗi sang: {RETRY_FOLDER}")

    if missing:
        missing_file = Path(RETRY_FOLDER) / "missing_files.txt"
        with open(missing_file, "w", encoding="utf-8") as f:
            for name in missing:
                f.write(name + "\n")

        print(f"Có {len(missing)} file không tìm thấy.")
        print(f"Đã ghi danh sách thiếu vào: {missing_file}")


if __name__ == "__main__":
    main()
