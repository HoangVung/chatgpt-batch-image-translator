import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.runtime import make_default_settings, save_settings
from resource_guard import (ResourceConflict, ResourceLease, browser_profiles_in_use, canonical_path,
                            claim_output, validate_output_names, validate_resources, workflow_resources)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream: stream.close()
        self.temp.cleanup()

    def config(self, key):
        cfg = make_default_settings(self.root / key)
        Path(cfg["image_folder"]).mkdir(parents=True)
        return cfg

    def spawn(self, cfg):
        path = self.root / (str(len(self.children)) + "-settings.json")
        save_settings(path, cfg)
        env = dict(os.environ, BATCH_TRANSLATOR_SETTINGS_FILE=str(path), PYTHONIOENCODING="utf-8")
        for key in ("IMAGE_FOLDER", "DOWNLOAD_FOLDER", "PROFILE_DIR", "SERVICE", "RUN_MODE", "START_FROM", "BATCH_SIZE", "AUTO_ACCOUNT_FALLBACK_ENABLED"):
            env.pop(key, None)
        child = subprocess.Popen([sys.executable, "-u", str(ROOT / "tests/fixtures/parallel_worker.py"), str(self.root / "locks")],
                                 env=env, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.children.append(child)
        return child

    def ready(self, child):
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(child.stdout.readline()), daemon=True).start()
        result = lines.get(timeout=20)
        if result.strip() != "READY":
            child.wait(timeout=10)
            self.fail(result + child.stderr.read())

    def test_two_real_workers_keep_identically_named_pages_and_checkpoints_separate(self):
        a, b = self.config("A"), self.config("B")
        for cfg, color in ((a, "red"), (b, "blue")):
            Image.new("RGB", (16, 16), color).save(Path(cfg["image_folder"]) / "1_1.jpg")
        pa, pb = self.spawn(a), self.spawn(b)
        self.ready(pa)
        self.ready(pb)
        outputs = [Path(cfg["download_folder"]) / "00001_00001VN.png" for cfg in (a, b)]
        hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs]
        self.assertNotEqual(hashes[0], hashes[1])
        self.assertIsNone(pa.poll())
        self.assertIsNone(pb.poll())
        duplicate = self.spawn(a)
        _, error = duplicate.communicate(timeout=20)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("Folder conflict", error)
        for cfg in (a, b):
            directory = Path(cfg["download_folder"])
            checkpoint = json.loads((directory / "job_checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(canonical_path(checkpoint["output_folder"]), canonical_path(directory))
            self.assertEqual(checkpoint["active_account"]["profile_dir"], cfg["profile_dir"])
            self.assertIn("1_1.jpg", (directory / "progress.csv").read_text(encoding="utf-8-sig"))
        pa.kill()
        pa.wait(timeout=10)
        self.assertIsNone(pb.poll())
        self.assertEqual(hashlib.sha256(outputs[1].read_bytes()).hexdigest(), hashes[1])
        # Dead OS lock is reclaimed; surviving worker's resources remain busy.
        replacement = self.spawn(a)
        self.ready(replacement)
        replacement.communicate("\n", timeout=20)
        pb.communicate("\n", timeout=20)
        self.assertEqual(pb.returncode, 0)

    def test_rejects_nested_output_profile_source_and_duplicate_names(self):
        cfg = self.config("A")
        cfg["download_folder"] = str(Path(cfg["image_folder"]) / "translated")
        with self.assertRaises(ResourceConflict): workflow_resources(cfg)
        with self.assertRaises(ResourceConflict):
            validate_output_names([Path("1_1.jpg"), Path("01_01.png")], lambda p: "00001_00001VN.png")

    def test_four_real_workers_survive_one_kill_and_keep_resources_isolated(self):
        settings = [self.config(key) for key in ("A", "B", "C", "D")]
        for cfg, color in zip(settings, ("red", "blue", "green", "yellow")):
            Image.new("RGB", (16, 16), color).save(Path(cfg["image_folder"]) / "1_1.jpg")
        processes = [self.spawn(cfg) for cfg in settings]
        for process in processes:
            self.ready(process)
        self.assertEqual(len({process.pid for process in processes}), 4)
        self.assertTrue(all(process.poll() is None for process in processes))
        outputs = [Path(cfg["download_folder"]) / "00001_00001VN.png" for cfg in settings]
        hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs]
        self.assertEqual(len(set(hashes)), 4)
        for cfg in settings:
            output = Path(cfg["download_folder"])
            checkpoint = json.loads((output / "job_checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(canonical_path(checkpoint["output_folder"]), canonical_path(output))
            self.assertEqual(checkpoint["active_account"]["profile_dir"], cfg["profile_dir"])
            self.assertIn("1_1.jpg", (output / "progress.csv").read_text(encoding="utf-8-sig"))
            ownership = json.loads((output / "workflow_output.json").read_text(encoding="utf-8"))
            self.assertEqual(canonical_path(ownership["source_folder"]), canonical_path(cfg["image_folder"]))
        # Kill the newly added Book 3; the other three remain alive and locked.
        processes[2].kill()
        processes[2].wait(timeout=10)
        for index in (0, 1, 3):
            self.assertIsNone(processes[index].poll())
            self.assertEqual(hashlib.sha256(outputs[index].read_bytes()).hexdigest(), hashes[index])
            duplicate = self.spawn(settings[index])
            _, error = duplicate.communicate(timeout=20)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("Folder conflict", error)
        replacement = self.spawn(settings[2])
        self.ready(replacement)
        self.assertEqual(hashlib.sha256(outputs[2].read_bytes()).hexdigest(), hashes[2])
        for process in (processes[0], processes[1], replacement, processes[3]):
            process.communicate("\n", timeout=20)
            self.assertEqual(process.returncode, 0)

    def test_aliases_and_fallback_pool_are_exclusive(self):
        cfg = self.config("A")
        cfg["chatgpt_accounts"].append({"id": "fallback", "name": "fallback", "profile_dir": str(self.root / "fallback")})
        resources = workflow_resources(cfg)
        self.assertIn(canonical_path(self.root / "fallback"), [r["path"] for r in resources])
        with ResourceLease(resources, directory=self.root / "locks", inspect_browsers=False):
            path = str(self.root / "fallback" / ".." / "fallback")
            if os.name == "nt": path = path.upper()
            with self.assertRaises(ResourceConflict):
                with ResourceLease([{"kind": "profile", "path": canonical_path(path)}], directory=self.root / "locks", inspect_browsers=False): pass

    @unittest.skipUnless(os.name == "nt", "Windows junction")
    def test_junction_alias_is_resolved(self):
        import _winapi
        actual, link = self.root / "actual", self.root / "alias"
        actual.mkdir()
        _winapi.CreateJunction(str(actual), str(link))
        self.assertEqual(canonical_path(actual), canonical_path(link))

    def test_output_ownership_prevents_wrong_book_resume_and_preserves_existing_bytes(self):
        cfg = self.config("A")
        claim_output(cfg)
        output = Path(cfg["download_folder"])
        (output / "keep.png").write_bytes(b"keep")
        other = self.config("B")
        other["download_folder"] = str(output)
        with self.assertRaises(ResourceConflict): claim_output(other, allow_legacy=True)
        self.assertEqual((output / "keep.png").read_bytes(), b"keep")

    def test_orphan_browser_profile_is_not_reclaimed(self):
        cfg = self.config("A")
        with patch("resource_guard.browser_profiles_in_use", return_value={canonical_path(cfg["profile_dir"])}):
            with self.assertRaisesRegex(ResourceConflict, "already open"):
                with ResourceLease(workflow_resources(cfg), directory=self.root / "locks"): pass

    def test_log_export_can_share_only_its_own_workers_output(self):
        cfg = self.config("A")
        directory = self.root / "locks"
        output = [{"kind": "output", "path": canonical_path(cfg["download_folder"])}]
        profile = [{"kind": "profile", "path": canonical_path(cfg["profile_dir"])}]
        with ResourceLease(workflow_resources(cfg), directory=directory, inspect_browsers=False):
            with ResourceLease(output, directory=directory, shared_output_pid=os.getpid()): pass
            with self.assertRaises(ResourceConflict):
                with ResourceLease(output, directory=directory, shared_output_pid=os.getpid() + 1): pass
            with self.assertRaises(ResourceConflict):
                with ResourceLease(profile, directory=directory, shared_output_pid=os.getpid(), inspect_browsers=False): pass

    @unittest.skipUnless(os.name == "nt", "Windows process command line")
    def test_browser_inventory_understands_spaces_and_unicode(self):
        profile = self.root / "profile sách A"
        for argument in ('"--user-data-dir=' + str(profile) + '"', '--user-data-dir="' + str(profile) + '"'):
            result = subprocess.CompletedProcess([], 0, json.dumps(["chrome.exe " + argument]), "")
            with patch("resource_guard.subprocess.run", return_value=result):
                self.assertEqual(browser_profiles_in_use(), {canonical_path(profile)})

    def test_snapshot_failure_does_not_fall_back_to_root_config(self):
        cfg = self.config("A")
        env = dict(os.environ, BATCH_TRANSLATOR_SETTINGS_FILE=str(self.root / "missing.json"), PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, "-c", "import run_chatgpt_batch"], cwd=ROOT, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FileNotFoundError", result.stderr)
        self.assertFalse(Path(cfg["download_folder"]).exists())

    @unittest.skipUnless(os.name == "nt", "Windows browser process inventory")
    def test_real_browser_with_unicode_profile_is_detected(self):
        from playwright.sync_api import sync_playwright
        profile = self.root / "profile sách đang mở"
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile), executable_path=playwright.chromium.executable_path, headless=True)
            try:
                self.assertIn(canonical_path(profile), browser_profiles_in_use())
                with self.assertRaisesRegex(ResourceConflict, "already open"):
                    with ResourceLease([{"kind": "profile", "path": canonical_path(profile)}], directory=self.root / "locks"):
                        pass
            finally:
                context.close()


if __name__ == "__main__":
    unittest.main()
