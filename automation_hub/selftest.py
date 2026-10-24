from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .google_blogger import validate_google_desktop_client_config
from .i18n import SUPPORTED_LOCALES, tr
from .scheduler import WindowsTaskScheduler
from .storage import DPAPITokenVault


def run_self_test() -> dict[str, Any]:
    results: dict[str, Any] = {}

    translations: dict[str, str] = {}
    for locale in SUPPORTED_LOCALES:
        title = tr(locale, "app_title")
        if not title or title == "app_title":
            raise RuntimeError(f"Translation resource failed: {locale}")
        translations[locale] = title
    results["i18n"] = translations

    metadata = validate_google_desktop_client_config({
        "installed": {
            "client_id": "1234567890-selftest.apps.googleusercontent.com",
            "client_secret": "self-test-only",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    })
    results["google_oauth_validation"] = metadata.client_id.endswith(".apps.googleusercontent.com")

    if os.name == "nt":
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "vault.dpapi"
            vault = DPAPITokenVault(path)
            secret = "WorkflowAutomationHub-self-test"
            vault.save_text(secret)
            encrypted = path.read_bytes()
            if secret.encode("utf-8") in encrypted:
                raise RuntimeError("DPAPI self-test found plaintext in encrypted file")
            if vault.load_text() != secret:
                raise RuntimeError("DPAPI self-test round-trip failed")
            vault.delete()
        results["dpapi"] = True

        scheduler = WindowsTaskScheduler().check()
        if not scheduler.ok:
            raise RuntimeError(f"Task Scheduler self-test failed: {scheduler.detail}")
        results["task_scheduler"] = True
    else:
        results["dpapi"] = "skipped_non_windows"
        results["task_scheduler"] = "skipped_non_windows"

    results["ok"] = True
    return results


def format_self_test(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True)
