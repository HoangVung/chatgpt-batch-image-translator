"""Filesystem ownership and OS-backed leases, shared by desktop and worker.

No browser/UI imports. The index mutex serializes claims; each running worker
holds its own lease file open. A killed worker cannot leave an active file lock.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class ResourceConflict(ValueError):
    pass


def canonical_path(value):
    if not str(value or "").strip():
        raise ResourceConflict("Chưa chọn thư mục / Folder is required.")
    return os.path.normcase(str(Path(value).expanduser().resolve()))


def overlaps(left, right):
    try:
        return os.path.commonpath([left, right]) in (left, right)
    except ValueError:
        return False


def configured_profiles(settings):
    values = [a.get("profile_dir") for a in settings.get("chatgpt_accounts", [])]
    values += [a.get("profile_dir") for a in settings.get("gemini_accounts", [])]
    values += [settings.get("profile_dir"), settings.get("gemini_profile_dir")]
    return sorted({canonical_path(p) for p in values if p})


def workflow_resources(settings, mode="main"):
    active = canonical_path(settings.get("profile_dir"))
    profiles = {active}
    if mode != "login" and settings.get("service", "chatgpt") == "chatgpt" and settings.get("auto_account_fallback_enabled", True):
        profiles.update(canonical_path(a["profile_dir"]) for a in settings.get("chatgpt_accounts", []))
    result = [{"kind": "profile", "path": p} for p in sorted(profiles)]
    if mode != "login":
        result += [{"kind": "source", "path": canonical_path(settings.get("image_folder"))},
                   {"kind": "output", "path": canonical_path(settings.get("download_folder"))}]
    validate_resources(result)
    return result


def validate_resources(resources, other=()):
    pairs = ((a, b) for a in resources for b in other) if other else (
        (a, b) for i, a in enumerate(resources) for b in resources[i + 1:])
    for a, b in pairs:
        if a["kind"] == b["kind"] == "source":
            continue
        if overlaps(a["path"], b["path"]):
            raise ResourceConflict(
                f"Xung đột thư mục / Folder conflict ({a['kind']} / {b['kind']}): "
                f"{a['path']} ↔ {b['path']}. Chọn thư mục riêng / Choose separate folders.")


def registry_dir():
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    return Path(base or tempfile.gettempdir()) / "ChatGPT Batch Translator" / "resource-locks"


def _lock(stream, blocking=False):
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))


def _unlock(stream):
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _open_lock(path):
    # Byte-range locks may extend past EOF. Do not initialize a marker byte:
    # another process may already hold that byte between open and write.
    return open(path, "a+b")


@contextmanager
def _index_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    stream = _open_lock(directory / "index.lock")
    locked = False
    try:
        deadline = time.monotonic() + 15
        while not locked:
            try:
                _lock(stream)
                locked = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise ResourceConflict("Bộ quản lý tài nguyên đang bận / Resource manager is busy.")
                time.sleep(0.05)
        yield
    finally:
        if locked:
            _unlock(stream)
        stream.close()


def browser_profiles_in_use():
    """Detect orphan browsers even after their worker's lease was released.

    Only process command lines are inspected; cookies/profile contents are never
    read. A failed Windows inventory is an error, not permission to reuse profiles.
    """
    commands = []
    if os.name == "nt":
        command = ("$ErrorActionPreference = 'Stop'; [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                   "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe' OR Name = 'msedge.exe' OR Name = 'chromium.exe'\" "
                   "| Select-Object -ExpandProperty CommandLine | ConvertTo-Json -Compress")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                creationflags=subprocess.CREATE_NO_WINDOW, timeout=12)
        if result.returncode:
            raise ResourceConflict("Không kiểm tra được browser đang chạy / Cannot inspect running browsers.")
        raw = json.loads(result.stdout.strip() or "[]")
        commands = [raw] if isinstance(raw, str) else (raw or [])
    elif Path("/proc").exists():
        for path in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                args = path.read_bytes().decode(errors="replace").split("\0")
                commands.extend('"' + arg + '"' for arg in args if arg.startswith("--user-data-dir="))
            except (OSError, UnicodeError):
                continue
    else:
        result = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, check=True)
        commands = result.stdout.splitlines()
    found = set()
    for command in commands:
        if not command:
            continue
        for match in re.finditer(r'"--user-data-dir=([^"]+)"|--user-data-dir="([^"]+)"|--user-data-dir=([^"\s]+)', command):
            found.add(canonical_path(next(group for group in match.groups() if group is not None)))
    return found


class ResourceLease:
    def __init__(self, resources, *, directory=None, inspect_browsers=True, shared_output_pid=None):
        self.resources = resources
        self.directory = Path(directory) if directory else registry_dir()
        self.inspect_browsers = inspect_browsers
        self.shared_output_pid = shared_output_pid
        self.stream = None
        self.path = self.directory / (uuid.uuid4().hex + ".json")

    def __enter__(self):
        validate_resources(self.resources)
        with _index_lock(self.directory):
            for path in self.directory.glob("*.json"):
                lock_path = path.with_suffix(".lock")
                probe = _open_lock(lock_path)
                active = False
                try:
                    try:
                        _lock(probe)
                    except OSError:
                        active = True
                    if active:
                        try:
                            owner = json.loads(path.read_text(encoding="utf-8"))
                            # The UI may export a log alongside its own worker,
                            # but cannot borrow any profile or another output.
                            shares_own_output = self.shared_output_pid is not None and self.shared_output_pid == owner.get("pid") and all(
                                resource["kind"] == "output" and any(
                                    held["kind"] == "output" and held["path"] == resource["path"]
                                    for held in owner["resources"])
                                for resource in self.resources)
                            if not shares_own_output:
                                validate_resources(self.resources, owner["resources"])
                        except (KeyError, json.JSONDecodeError) as exc:
                            raise ResourceConflict("Khóa tài nguyên không hợp lệ / Invalid resource lease.") from exc
                    else:
                        _unlock(probe)
                finally:
                    probe.close()
                if not active:
                    path.unlink(missing_ok=True)
                    lock_path.unlink(missing_ok=True)
            if self.inspect_browsers:
                requested = [r["path"] for r in self.resources if r["kind"] == "profile"]
                if requested:
                    for busy in browser_profiles_in_use():
                        if any(overlaps(busy, path) for path in requested):
                            raise ResourceConflict(f"Profile đang mở / Profile is already open: {busy}")
            self.stream = _open_lock(self.path.with_suffix(".lock"))
            try:
                _lock(self.stream)
                self.path.write_text(json.dumps({"pid": os.getpid(), "resources": self.resources}), encoding="utf-8")
            except BaseException:
                self.stream.close()
                self.stream = None
                raise
        return self

    def __exit__(self, *_):
        if self.stream is not None:
            with _index_lock(self.directory):
                self.path.unlink(missing_ok=True)
                _unlock(self.stream)
                self.stream.close()
                self.stream = None
                self.path.with_suffix(".lock").unlink(missing_ok=True)


def claim_output(settings, *, allow_legacy=False, write=True):
    """Called under an output lease, before any progress/checkpoint write."""
    source = canonical_path(settings.get("image_folder"))
    output = Path(canonical_path(settings.get("download_folder")))
    if not Path(source).is_dir():
        raise ResourceConflict(f"Không tìm thấy nguồn / Source folder not found: {source}")
    destination = output / "workflow_output.json"
    if destination.exists():
        owner = json.loads(destination.read_text(encoding="utf-8"))
        if owner.get("version") != 1 or canonical_path(owner.get("source_folder")) != source:
            raise ResourceConflict("Kết quả thuộc sách khác / Output belongs to another book. Chọn thư mục khác.")
        return
    if output.exists() and any(output.iterdir()) and not allow_legacy:
        raise ResourceConflict("Thư mục có kết quả cũ chưa xác nhận nguồn. Dùng nút 'Xác nhận kết quả cũ' sau khi kiểm tra đúng sách / Confirm existing output belongs to this book.")
    if not write:
        return
    output.mkdir(parents=True, exist_ok=True)
    from desktop.runtime import save_settings
    save_settings(destination, {"version": 1, "source_folder": source})


def validate_output_names(images, output_name):
    names = {}
    for image in images:
        name = os.path.normcase(output_name(image))
        if name in names:
            raise ResourceConflict(f"Hai ảnh trùng tên đầu ra / Duplicate output name: {names[name]} / {image.name} → {name}")
        names[name] = image.name
