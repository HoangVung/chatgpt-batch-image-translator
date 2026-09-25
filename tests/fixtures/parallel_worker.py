"""Offline worker fixture: real config/guard/progress/output, no network or AI."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import resource_guard
import run_chatgpt_batch as worker
from PIL import Image

resource_guard.registry_dir = lambda: Path(sys.argv[1])
resource_guard.browser_profiles_in_use = lambda: set()


def offline_main():
    worker.ensure_dirs()
    images = worker.get_images()
    worker.init_progress()
    for index, source in enumerate(images, 1):
        target = Path(worker.DOWNLOAD_FOLDER) / worker.get_output_name(source)
        with Image.open(source) as image:
            image.save(target, format="PNG")
        worker.write_progress(index, source.name, target.name, "done", "offline fixture")
    worker.write_job_checkpoint(job_id="fixture", mode="main", images=images, batch=images,
                                position=len(images), current_image="", active_account=worker.get_chatgpt_accounts()[0],
                                stage="finished", state="complete", account_states={})
    print("READY", flush=True)
    sys.stdin.readline()
    return 0


worker.main = offline_main
raise SystemExit(worker.run_guarded())
