from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import settings_path

DEFAULTS: dict[str, Any] = {
    "locale": "ja",
    "google_client_id_hint": "",
    "google_project_id": "",
}
ALLOWED_KEYS = set(DEFAULTS)


class SettingsError(RuntimeError):
    pass


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings_path()

    def _quarantine_corrupt(self) -> Path | None:
        if not self.path.exists():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        counter = 1
        while target.exists():
            target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}-{counter}")
            counter += 1
        try:
            os.replace(self.path, target)
        except OSError:
            # A locked/read-only corrupt file must not prevent the desktop app
            # from opening. Saving new settings may still fail later, at which
            # point save() reports that failure explicitly.
            return None
        return target

    def load(self) -> dict[str, Any]:
        data = dict(DEFAULTS)
        if not self.path.exists():
            return data
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings root must be an object")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            self._quarantine_corrupt()
            return data

        for key in ALLOWED_KEYS:
            if key in raw:
                data[key] = raw[key]
        locale = str(data.get("locale", "ja"))
        data["locale"] = locale if locale in {"ja", "en"} else "ja"

        # One-release migration hint only. It is intentionally never written back.
        legacy_path = raw.get("google_credentials_file")
        if isinstance(legacy_path, str) and legacy_path.strip():
            data["_legacy_google_credentials_file"] = legacy_path.strip()
        return data

    def save(self, data: dict[str, Any]) -> None:
        clean = dict(DEFAULTS)
        for key in ALLOWED_KEYS:
            if key in data:
                clean[key] = data[key]
        locale = str(clean.get("locale", "ja"))
        clean["locale"] = locale if locale in {"ja", "en"} else "ja"

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(clean, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_name, self.path)
        except OSError as exc:
            raise SettingsError(f"Could not save settings / 設定を保存できません: {exc}") from exc
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
