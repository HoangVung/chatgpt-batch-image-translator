"""Stable machine-local browser storage for Windows cloud-synced workspaces.

Preparing a profile must happen while the caller holds its resource lease for
both the configured path and ``effective_profile_dir``. Mapping alone never
creates directories or reads browser credentials.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


_IS_WINDOWS = sys.platform == "win32"
_CACHE_DIRECTORIES = {
    "Cache", "Code Cache", "GPUCache", "ShaderCache", "GrShaderCache",
    "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "GraphiteDawnCache",
}
_TRANSIENT_FILES = {"SingletonCookie", "SingletonLock", "SingletonSocket", "DevToolsActivePort"}


class ProfilePreparationError(RuntimeError):
    """The original profile is intact, but its launch directory is unavailable."""


def _canonical(value):
    return os.path.normcase(str(Path(value).expanduser().resolve()))


def _inside(path, parent):
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:
        return False


def _local_profile_root():
    local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return local / "ChatGPT Batch Translator" / "browser-profiles"


def effective_profile_dir(configured):
    """Return a deterministic launch path; explicit local profiles stay local."""
    source = Path(configured).expanduser().resolve()
    if not _IS_WINDOWS:
        return source
    canonical = _canonical(source)
    root = _local_profile_root()
    # An already mapped path must not acquire another hash, even if a user has
    # placed LOCALAPPDATA beneath a directory with a cloud-provider name.
    if _inside(canonical, _canonical(root)):
        return source
    paths = (Path(configured).expanduser(), source)
    cloud = any(
        part.casefold() in {"my drive", "google drive", "onedrive"}
        or part.casefold().startswith("onedrive - ")
        for path in paths for part in path.parts
    )
    cloud = cloud or any(
        _inside(canonical, _canonical(value))
        for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
        if (value := os.environ.get(key))
    )
    if not cloud:
        return source
    name = re.sub(r"[^\w.-]+", "-", source.name.casefold()).strip(".-")[:64] or "profile"
    identity = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    return root / f"{name}-{identity}"


def _copy_ignore(source):
    def ignore(directory, names):
        relative = Path(directory).relative_to(source)
        is_profile = len(relative.parts) == 1 and (
            relative.name == "Default" or re.fullmatch(r"Profile \d+", relative.name)
        )
        ignored = set()
        if not relative.parts:
            ignored.update(name for name in names if name in _TRANSIENT_FILES)
        if not relative.parts or is_profile:
            ignored.update(name for name in names if name in _CACHE_DIRECTORIES)
        return ignored
    return ignore


def prepare_profile_dir(configured):
    """Copy a legacy cloud profile once, atomically, without modifying it.

    Cookies, Local State (including Chromium's encryption key), Local Storage,
    and IndexedDB are copied together. Copy failure never publishes a partial
    destination, so the next launch can retry from the intact source.
    """
    source = Path(configured).expanduser().resolve()
    target = effective_profile_dir(configured)
    staging = None
    try:
        if _canonical(source) == _canonical(target):
            target.mkdir(parents=True, exist_ok=True)
            return target
        if target.exists():
            if not target.is_dir():
                raise NotADirectoryError(str(target))
            return target
        if _inside(_canonical(target), _canonical(source)):
            raise ValueError("Local browser storage must be outside the original profile")
        try:
            source.stat()
        except FileNotFoundError:
            has_source = False
        else:
            if not source.is_dir():
                raise NotADirectoryError(str(source))
            has_source = True
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.migrating-", dir=target.parent))
        if has_source:
            shutil.copytree(source, staging, symlinks=True, dirs_exist_ok=True, ignore=_copy_ignore(source))
        # ResourceLease prevents other app workers from publishing this path.
        # rename (not replace) also refuses an existing destination on Windows.
        staging.rename(target)
        return target
    except (OSError, ValueError) as exc:
        raise ProfilePreparationError(
            f"Không chuẩn bị được profile đăng nhập / Cannot prepare browser profile: {target}. "
            "Profile gốc được giữ nguyên; hãy đóng browser và thử lại / "
            "The original profile is unchanged; close its browser and retry."
        ) from exc
    finally:
        if staging is not None and staging.exists():
            # Only remove the temporary directory created by this attempt.
            if staging.resolve().parent == target.parent.resolve():
                shutil.rmtree(staging, ignore_errors=True)
