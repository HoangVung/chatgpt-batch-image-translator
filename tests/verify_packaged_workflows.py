"""Opt-in smoke for a built windowed EXE, using empty isolated books only.

Usage: python tests/verify_packaged_workflows.py PATH_TO_EXE
No sign-in, browser workflow, external requests or production output is used.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.runtime import build_process_launch, make_default_settings, write_launch_snapshot
from resource_guard import ResourceLease, workflow_resources


def verify(executable):
    executable = Path(executable).resolve()
    results = []
    rejected = []
    with tempfile.TemporaryDirectory(prefix="parallel-exe-") as directory:
        base = Path(directory)
        processes = []
        try:
            for name in ("book-A", "book-B"):
                settings = make_default_settings(base / name)
                source = Path(settings["image_folder"])
                source.mkdir(parents=True)
                snapshot = write_launch_snapshot(settings, base / "snapshots")
                launch = build_process_launch(settings, "main", app_dir=executable.parent,
                                              executable=str(executable), frozen=True,
                                              data_dir=base / name, settings_file=snapshot)
                process = subprocess.Popen(launch.command, cwd=base, env=launch.env,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, encoding="utf-8", errors="replace",
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                processes.append((process, settings))
            for process, settings in processes:
                stdout, stderr = process.communicate(timeout=45)
                output = Path(settings["download_folder"])
                result_lines = [line for line in stdout.splitlines() if line.startswith("__BATCH_RESULT__=")]
                results.append({"exit_code": process.returncode, "stdout_chars": len(stdout),
                                "stderr": stderr[-1000:], "result_protocol": bool(result_lines),
                                "progress_exists": (output / "progress.csv").is_file(),
                                "ownership_exists": (output / "workflow_output.json").is_file()})
                if (output / "workflow_output.json").exists():
                    owner = json.loads((output / "workflow_output.json").read_text(encoding="utf-8"))
                    assert Path(owner["source_folder"]) == Path(settings["image_folder"]), owner
            # Failure paths must exit too, rather than waiting on a hidden
            # PyInstaller exception dialog in a --windowed build.
            def expect_rejection(environment, reason):
                process = subprocess.Popen(launch.command, cwd=base, env=environment,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, encoding="utf-8", errors="replace",
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                processes.append((process, settings))
                stdout, stderr = process.communicate(timeout=30)
                assert process.returncode == 1 and reason in stdout + stderr, (process.returncode, stdout, stderr)
                rejected.append({"reason": reason, "exit_code": process.returncode})

            expect_rejection(dict(launch.env, BATCH_TRANSLATOR_SETTINGS_FILE=str(base / "missing.json")), "FileNotFoundError")
            with ResourceLease(workflow_resources(settings), inspect_browsers=False):
                expect_rejection(launch.env, "Folder conflict")
        finally:
            for process, _ in processes:
                if process.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                    process.wait(timeout=10)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream and not stream.closed:
                        stream.close()
    print(json.dumps({"workers": results, "rejected": rejected}, ensure_ascii=False, indent=2))
    assert len(results) == 2 and all(
        item["exit_code"] == 0 and item["progress_exists"] and item["ownership_exists"] and item["result_protocol"]
        for item in results), "Frozen workers must deliver isolated outputs AND their completion protocol"


if __name__ == "__main__":
    verify(sys.argv[1])
