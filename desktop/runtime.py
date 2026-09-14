"""Pure settings and worker launch helpers shared by desktop shells."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from desktop_controller import ProcessLaunch


SETTINGS_KEYS = {
    "image_folder",
    "download_folder",
    "profile_dir",
    "gemini_profile_dir",
    "chatgpt_accounts",
    "active_chatgpt_account_id",
    "auto_account_fallback_enabled",
    "batch_size",
    "start_from",
    "auto_next_enabled",
    "auto_next_delay_minutes",
    "theme",
    "ui_style",
    "language",
    "service",
}
FORM_KEYS = {
    "image_folder",
    "download_folder",
    "profile_dir",
    "batch_size",
    "start_from",
    "auto_next_enabled",
    "auto_next_delay_minutes",
    "auto_account_fallback_enabled",
    "theme",
    "language",
    "service",
}
STRING_FORM_KEYS = FORM_KEYS - {"auto_next_enabled", "auto_account_fallback_enabled"}


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def get_data_dir(app_dir: Path | None = None) -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ChatGPT Batch Translator"
    return Path(app_dir or get_app_dir())


def make_default_settings(data_dir: Path) -> dict[str, Any]:
    return {
        "image_folder": str(data_dir / "images"),
        "download_folder": str(data_dir / "images_vn"),
        "profile_dir": str(data_dir / "chatgpt_auto_profile"),
        "gemini_profile_dir": str(data_dir / "gemini_auto_profile"),
        "chatgpt_accounts": [{
            "id": "default",
            "name": "ChatGPT 1",
            "profile_dir": str(data_dir / "chatgpt_auto_profile"),
        }],
        "active_chatgpt_account_id": "default",
        "auto_account_fallback_enabled": True,
        "batch_size": "10",
        "start_from": "",
        "auto_next_enabled": True,
        "auto_next_delay_minutes": "2",
        "theme": "system",
        "ui_style": "classic",
        "language": "vi",
        "service": "chatgpt",
    }


def copy_default_settings(defaults: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **defaults,
        "chatgpt_accounts": [dict(account) for account in defaults["chatgpt_accounts"]],
    }


def load_settings(path: Path, defaults: Mapping[str, Any]) -> dict[str, Any]:
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("settings root must be an object")
            settings = {**copy_default_settings(defaults), **saved}
            if "chatgpt_accounts" not in saved:
                settings["chatgpt_accounts"] = []
            if "active_chatgpt_account_id" not in saved:
                settings["active_chatgpt_account_id"] = ""
            if "gemini_profile_dir" not in saved:
                settings["gemini_profile_dir"] = ""
            return settings
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    return copy_default_settings(defaults)


def save_settings(path: Path, settings: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(settings), ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_chatgpt_accounts(settings: dict[str, Any], data_dir: Path) -> list[dict[str, str]]:
    accounts: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    raw_accounts = settings.get("chatgpt_accounts", [])
    if isinstance(raw_accounts, list):
        for raw in raw_accounts:
            if not isinstance(raw, dict):
                continue
            account_id = str(raw.get("id", "")).strip()
            name = str(raw.get("name", "")).strip()
            profile_dir = str(raw.get("profile_dir", "")).strip()
            folded = name.casefold()
            if not account_id or not profile_dir or account_id in seen_ids or folded in seen_names:
                continue
            accounts.append({"id": account_id, "name": name, "profile_dir": profile_dir})
            seen_ids.add(account_id)
            seen_names.add(folded)

    service = str(settings.get("service", "chatgpt")).lower()
    legacy_profile = str(settings.get("profile_dir", "")).strip()
    if not accounts:
        profile = legacy_profile if service == "chatgpt" and legacy_profile else str(data_dir / "chatgpt_auto_profile")
        accounts = [{"id": "default", "name": "ChatGPT 1", "profile_dir": profile}]

    account_ids = {account["id"] for account in accounts}
    active_id = str(settings.get("active_chatgpt_account_id", "")).strip()
    if active_id not in account_ids:
        active_id = next(
            (account["id"] for account in accounts if service == "chatgpt" and account["profile_dir"] == legacy_profile),
            accounts[0]["id"],
        )

    gemini_profile = str(settings.get("gemini_profile_dir", "")).strip()
    if not gemini_profile:
        gemini_profile = legacy_profile if service == "gemini" and legacy_profile else str(data_dir / "gemini_auto_profile")

    settings["chatgpt_accounts"] = accounts
    settings["active_chatgpt_account_id"] = active_id
    settings["gemini_profile_dir"] = gemini_profile
    return accounts


def get_active_chatgpt_account(settings: dict[str, Any], data_dir: Path) -> dict[str, str]:
    accounts = normalize_chatgpt_accounts(settings, data_dir)
    active_id = settings["active_chatgpt_account_id"]
    return next(account for account in accounts if account["id"] == active_id)


def apply_form_settings(current: dict[str, Any], payload: Any, data_dir: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("settings payload must be an object")
    unknown = set(payload) - FORM_KEYS
    if unknown:
        raise ValueError(f"unsupported settings fields: {', '.join(sorted(unknown))}")
    for key in STRING_FORM_KEYS & payload.keys():
        value = payload[key]
        if not isinstance(value, str) or "\0" in value or len(value) > 32_768:
            raise ValueError(f"invalid value for {key}")
    for key in ("auto_next_enabled", "auto_account_fallback_enabled"):
        if key in payload and not isinstance(payload[key], bool):
            raise ValueError(f"invalid value for {key}")
    if payload.get("service", current.get("service")) not in {"chatgpt", "gemini"}:
        raise ValueError("service must be chatgpt or gemini")
    if payload.get("theme", current.get("theme")) not in {"system", "light", "dark"}:
        raise ValueError("theme must be system, light, or dark")
    if payload.get("language", current.get("language")) not in {"vi", "en"}:
        raise ValueError("language must be vi or en")

    updated = {**current, **payload}
    normalize_chatgpt_accounts(updated, data_dir)
    profile = str(updated.get("profile_dir", "")).strip()
    if updated["service"] == "chatgpt":
        account = get_active_chatgpt_account(updated, data_dir)
        if profile:
            account["profile_dir"] = profile
        updated["profile_dir"] = account["profile_dir"]
    else:
        if profile:
            updated["gemini_profile_dir"] = profile
        updated["profile_dir"] = updated["gemini_profile_dir"]
    return updated


def build_process_launch(
    settings: dict[str, Any],
    mode: str,
    *,
    app_dir: Path | None = None,
    executable: str | None = None,
    frozen: bool | None = None,
    environ: Mapping[str, str] | None = None,
    os_name: str | None = None,
) -> ProcessLaunch:
    if mode not in {"main", "retry", "force", "login"}:
        raise ValueError("unsupported run mode")
    app_dir = Path(app_dir or get_app_dir())
    executable = executable or sys.executable
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    os_name = os.name if os_name is None else os_name
    normalize_chatgpt_accounts(settings, get_data_dir(app_dir))
    service = settings.get("service", "chatgpt")
    profile = (
        get_active_chatgpt_account(settings, get_data_dir(app_dir))["profile_dir"]
        if service == "chatgpt"
        else settings["gemini_profile_dir"]
    )
    settings["profile_dir"] = profile

    env = dict(environ or os.environ)
    env.update({
        "IMAGE_FOLDER": str(settings.get("image_folder", "")),
        "DOWNLOAD_FOLDER": str(settings.get("download_folder", "")),
        "PROFILE_DIR": profile,
        "BATCH_SIZE": str(settings.get("batch_size", "")),
        "START_FROM": str(settings.get("start_from", "")),
        "RUN_MODE": mode,
        "SERVICE": str(service),
        "AUTO_ACCOUNT_FALLBACK_ENABLED": "1" if settings.get("auto_account_fallback_enabled", True) else "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
    })
    browser_path = app_dir / "ms-playwright"
    if frozen or browser_path.exists():
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_path)
    if os_name == "nt":
        python_dir = Path(executable).resolve().parent
        dll_dirs = [app_dir, python_dir, python_dir / "DLLs"]
        env["PATH"] = os.pathsep.join([str(path) for path in dll_dirs if path.exists()] + [env.get("PATH", "")])

    command = [executable, "--worker"] if frozen else [executable, "-u", str(app_dir / "run_chatgpt_batch.py")]
    creationflags = subprocess_creationflags(os_name)
    return ProcessLaunch(command, str(app_dir), env, creationflags)


def subprocess_creationflags(os_name: str) -> int:
    import subprocess

    return subprocess.CREATE_NO_WINDOW if os_name == "nt" else 0
