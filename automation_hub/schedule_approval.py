"""Approval guard for recurring Blogger writes.

This is a local accidental-change guard, not a security boundary against
someone with write access to the user's own application data directory.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import BloggerLinkJob
from .paths import app_data_dir
from .ui_flow import job_revision


class ScheduleApprovalError(RuntimeError):
    pass


class ScheduleApprovalStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else app_data_dir() / "schedule_approvals.json"

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ScheduleApprovalError("Could not read schedule approvals / 定期実行の承認情報を読めません") from exc
        if not isinstance(data, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) or len(value) != 64
            for key, value in data.items()
        ):
            raise ScheduleApprovalError("Invalid schedule approvals / 定期実行の承認情報が不正です")
        return data

    def approved(self, job: BloggerLinkJob) -> bool:
        return self._load().get(job.id) == job_revision(job)

    def _save(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix="schedule-approval-", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(values, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise ScheduleApprovalError("Could not save schedule approvals / 承認情報を保存できません") from exc
        finally:
            Path(temporary).unlink(missing_ok=True)

    def authorize(self, job: BloggerLinkJob) -> None:
        entries = self._load()
        entries[job.id] = job_revision(job)
        self._save(entries)

    def revoke(self, job_id: str) -> None:
        entries = self._load()
        if job_id in entries:
            del entries[job_id]
            self._save(entries)
