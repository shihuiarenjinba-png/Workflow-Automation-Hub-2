from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .paths import (
    app_data_dir,
    google_client_config_path,
    jobs_path,
    settings_path,
    token_path,
)
from .selftest import run_self_test


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_probe() -> bool:
    root = app_data_dir()
    try:
        fd, name = tempfile.mkstemp(prefix="support-write-probe-", suffix=".tmp", dir=root)
        os.close(fd)
        Path(name).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def collect_diagnostics(*, include_self_test: bool = True) -> dict[str, Any]:
    executable = Path(sys.executable)
    report: dict[str, Any] = {
        "schema_version": 1,
        "product": "Workflow Automation Hub",
        "app_version": __version__,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "privacy": {
            "contains_oauth_token": False,
            "contains_client_secret": False,
            "contains_username": False,
            "contains_full_paths": False,
            "note": "Credential contents, usernames, hostnames, and absolute paths are intentionally excluded.",
        },
        "windows": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "architecture": platform.architecture()[0],
        },
        "runtime": {
            "frozen_exe": bool(getattr(sys, "frozen", False)),
            "python_version": platform.python_version(),
            "executable_name": executable.name,
            "executable_sha256": sha256_file(executable) if executable.is_file() else None,
        },
        "local_state": {
            "app_data_write": _write_probe(),
            "settings_present": settings_path().exists(),
            "jobs_present": jobs_path().exists(),
            "google_client_config_present": google_client_config_path().exists(),
            "google_token_present": token_path().exists(),
        },
    }

    if include_self_test:
        try:
            report["self_test"] = {"ok": True, "result": run_self_test()}
        except Exception as exc:
            report["self_test"] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "note": "Error detail is intentionally omitted from the portable support report.",
            }
    else:
        report["self_test"] = {"ok": None, "skipped": True}

    report["overall_ok"] = bool(
        report["local_state"]["app_data_write"]
        and (report["self_test"]["ok"] is True or report["self_test"]["ok"] is None)
    )
    return report


def format_diagnostics(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_diagnostics(path: Path, *, include_self_test: bool = True) -> dict[str, Any]:
    report = collect_diagnostics(include_self_test=include_self_test)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_diagnostics(report), encoding="utf-8")
    return report
