"""Track image-quota recovery estimates independently of batch progress."""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

VIETNAM = timezone(timedelta(hours=7))
_TOKEN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(hours?|hrs?|giờ|minutes?|mins?|phút|days?|ngày|seconds?|secs?|giây)\b", re.I)
_START = re.compile(r"(?:resets?\s+in|try\s+again\s+in|có\s+thể\s+tạo[^.!?]*?sau|đặt\s+lại[^.!?]*?sau|thử\s+lại[^.!?]*?sau)\s+", re.I)


def reset_delay_seconds(evidence):
    """Read only a reset/wait duration, never guess a plan's quota period."""
    text = " ".join(str(evidence or "").split())
    for start in _START.finditer(text):
        tail = text[start.end():]
        total, position, found = 0.0, 0, False
        while True:
            match = _TOKEN.match(tail, position)
            if not match:
                break
            value = float(match.group(1).replace(",", "."))
            unit = match.group(2).casefold()
            multiplier = (86400 if unit.startswith("day") or unit == "ngày" else
                          3600 if unit.startswith(("hour", "hr")) or unit == "giờ" else
                          60 if unit.startswith(("minute", "min")) or unit == "phút" else 1)
            total += value * multiplier
            found = True
            separator = re.match(r"\s*(?:(?:and|và|,)\s*)?", tail[match.end():], re.I)
            position = match.end() + separator.end()
        if found and math.isfinite(total) and 0 <= total <= 366 * 86400:
            return total
    return None


def event_timestamp(value, fallback):
    try:
        if isinstance(value, str) and not re.fullmatch(r"[\d.]+", value):
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                return fallback
            value = stamp.timestamp()
        value = float(value)
        if not math.isfinite(value):
            return fallback
        datetime.fromtimestamp(value, timezone.utc)
        return value
    except (ValueError, TypeError, OverflowError, OSError):
        return fallback


class QuotaLimits:
    def __init__(self, path, clock=None):
        self.path = Path(path)
        self.clock = clock or time.time
        self._lock = threading.RLock()
        self.records = {}
        self._due_ids = set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data.get("accounts", []):
                if not isinstance(item, dict) or not item.get("account_id"):
                    continue
                record = {
                    "account_id": str(item["account_id"]),
                    "account_name": str(item.get("account_name") or "ChatGPT"),
                    "detected_at": event_timestamp(item.get("detected_at"), self.clock()),
                    "reset_at": event_timestamp(item.get("reset_at"), None),
                }
                self.records[record["account_id"]] = record
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def record(self, event):
        name = str(event.get("account_name") or "ChatGPT")
        identity = str(event.get("account_id") or name)
        detected = event_timestamp(event.get("detected_at"), self.clock())
        delay = reset_delay_seconds(event.get("evidence"))
        item = {
            "account_id": identity, "account_name": name,
            "detected_at": detected,
            "reset_at": detected + delay if delay is not None else None,
        }
        with self._lock:
            self.records[identity] = item
            self._save(self.records)
        return dict(item)

    def _save(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.path.with_suffix(".json.tmp")
        try:
            staging.write_text(json.dumps({"version": 1, "accounts": list(records.values())},
                                          ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(staging, self.path)
        finally:
            staging.unlink(missing_ok=True)

    def clear(self, account_id):
        """Remove a limit only after this account has successfully created an image."""
        identity = str(account_id or "")
        with self._lock:
            if identity not in self.records:
                return False
            remaining = dict(self.records)
            del remaining[identity]
            self._save(remaining)
            self.records = remaining
            return True

    def expire_due(self):
        """Refresh due estimates; elapsed time does not confirm account recovery."""
        with self._lock:
            now = self.clock()
            due = {
                identity for identity, item in self.records.items()
                if item["reset_at"] is not None and item["reset_at"] <= now
            }
            changed = due != self._due_ids
            self._due_ids = due
            return changed


    def snapshot(self, accounts=()):
        names = {str(item["id"]): item["name"] for item in accounts}
        with self._lock:
            result = []
            for stored in self.records.values():
                item = dict(stored)
                item["account_name"] = names.get(item["account_id"], item["account_name"])
                item["detected_vn"] = datetime.fromtimestamp(item["detected_at"], VIETNAM).strftime("%d/%m/%Y %H:%M")
                reset = item["reset_at"]
                item["reset_vn"] = datetime.fromtimestamp(reset, VIETNAM).strftime("%d/%m %H:%M") if reset is not None else None
                item["reset_vn_full"] = datetime.fromtimestamp(reset, VIETNAM).strftime("%d/%m/%Y %H:%M") if reset is not None else None
                item["estimate_due"] = reset is not None and reset <= self.clock()
                result.append(item)
            return result
