"""One-time, recoverable settings reset for the isolated book workers only."""
from copy import deepcopy
import base64
import hashlib
import json
import uuid
from pathlib import Path

from desktop.runtime import make_default_settings, save_settings
from resource_guard import ResourceLease, ResourceConflict, canonical_path, configured_profiles

RUN_KEYS = ("service", "batch_size", "auto_next_enabled", "auto_next_delay_minutes",
            "auto_account_fallback_enabled")


def reset_book(api, template):
    if api.session_id not in {"book-3", "book-4"}:
        raise ValueError("Reset is restricted to book-3/book-4")
    directory = api.data_dir / "books34-setup-v1"
    marker, journal = directory / "complete.json", directory / "pending.json"
    if marker.exists():
        return
    if api.controller.state.running or api.controller.is_running() or api.controller.state.auto_next_active:
        raise ResourceConflict("Dừng sách 3/4 trước khi đặt lại cấu hình.")
    resources = [{"kind": "output", "path": canonical_path(directory)}]
    if api.settings_path.exists():
        resources += [{"kind": "profile", "path": path} for path in configured_profiles(api.settings)]
        output = str(api.settings.get("download_folder", "")).strip()
        if output:
            resources.append({"kind": "output", "path": canonical_path(output)})
    with ResourceLease(resources):
        if marker.exists():
            return
        if journal.exists():
            transaction = json.loads(journal.read_text(encoding="utf-8"))
        else:
            original = api.settings_path.read_bytes() if api.settings_path.exists() else None
            profiles = api.data_dir / "isolated-profiles" / uuid.uuid4().hex
            target = make_default_settings(profiles)
            for key in RUN_KEYS:
                target[key] = deepcopy(template.settings[key])
            for key in ("theme", "language"):
                target[key] = template.settings[key]
            target.update(image_folder="", download_folder="", start_from="")
            target["profile_dir"] = (target["gemini_profile_dir"] if target["service"] == "gemini"
                                     else target["chatgpt_accounts"][0]["profile_dir"])
            transaction = {"version": 1, "template": template.session_id, "target": target,
                           "original_base64": base64.b64encode(original).decode() if original is not None else None,
                           "original_sha256": hashlib.sha256(original).hexdigest() if original is not None else None}
            save_settings(journal, transaction)
        original = transaction["original_base64"]
        if original is not None:
            raw = base64.b64decode(original, validate=True)
            if hashlib.sha256(raw).hexdigest() != transaction["original_sha256"]:
                raise ValueError("Invalid settings backup hash")
            backup = directory / "app_settings.original.json"
            # The journal contains the original bytes even if interrupted during backup.
            if not backup.exists():
                temporary = directory / "backup.part"
                temporary.write_bytes(raw)
                temporary.replace(backup)
            elif backup.read_bytes() != raw:
                raise ValueError("Existing settings backup differs; reset stopped")
        save_settings(api.settings_path, transaction["target"])
        save_settings(marker, {"version": 1, "template": transaction["template"],
                               "original_sha256": transaction["original_sha256"]})
        api.settings = deepcopy(transaction["target"])
        api._configure_controller()
