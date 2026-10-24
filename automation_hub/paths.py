from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "WorkflowAutomationHub2"


def app_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def jobs_path() -> Path:
    return app_data_dir() / "jobs.json"


def token_path() -> Path:
    return app_data_dir() / "google_token.dpapi"


def google_client_config_path() -> Path:
    return app_data_dir() / "google_client.dpapi"


def audit_log_path() -> Path:
    path = app_data_dir() / "logs" / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def blogger_backup_dir() -> Path:
    path = app_data_dir() / "backups" / "blogger"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_lock_dir() -> Path:
    path = app_data_dir() / "locks"
    path.mkdir(parents=True, exist_ok=True)
    return path
