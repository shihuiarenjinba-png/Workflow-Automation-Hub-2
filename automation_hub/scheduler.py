from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .models import BloggerLinkJob, ScheduleSpec, WEEKDAYS, validate_job_id, validate_time


class SchedulerError(RuntimeError):
    pass


@dataclass
class SchedulerCheck:
    ok: bool
    detail: str


def task_name(job_id: str) -> str:
    return f"WorkflowAutomationHub2_{validate_job_id(job_id)}"


def runner_command(job_id: str) -> str:
    safe_id = validate_job_id(job_id)
    if getattr(sys, "frozen", False):
        argv = [str(Path(sys.executable).resolve()), "--run-job", safe_id]
    else:
        entry = (Path(__file__).resolve().parent.parent / "desktop_app.py").resolve()
        argv = [str(Path(sys.executable).resolve()), str(entry), "--run-job", safe_id]
    return subprocess.list2cmdline(argv)


def build_create_args(job: BloggerLinkJob) -> list[str]:
    if not job.enabled:
        raise SchedulerError("Disabled jobs cannot be registered / 無効なジョブはスケジュール登録できません")
    schedule: ScheduleSpec = job.schedule
    args = [
        "schtasks", "/Create",
        "/TN", task_name(job.id),
        "/TR", runner_command(job.id),
        "/F",
        "/RL", "LIMITED",
        "/IT",
    ]
    if schedule.kind == "daily":
        args.extend(["/SC", "DAILY", "/ST", validate_time(schedule.time)])
    elif schedule.kind == "weekly":
        days = [day for day in WEEKDAYS if day in schedule.weekdays]
        if not days:
            raise SchedulerError("At least one weekday is required / 曜日を1つ以上選択してください")
        args.extend(["/SC", "WEEKLY", "/D", ",".join(days), "/ST", validate_time(schedule.time)])
    elif schedule.kind == "logon":
        args.extend(["/SC", "ONLOGON"])
    else:
        raise SchedulerError(f"Unsupported schedule kind / 未対応のスケジュール種別: {schedule.kind}")
    return args


class WindowsTaskScheduler:
    def check(self) -> SchedulerCheck:
        if os.name != "nt":
            return SchedulerCheck(False, "Windows Task Scheduler is available only on Windows / Windowsでのみ利用できます")
        if not shutil.which("schtasks"):
            return SchedulerCheck(False, "schtasks.exe was not found / schtasks.exeが見つかりません")
        try:
            result = subprocess.run(
                ["schtasks", "/Query", "/FO", "LIST"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return SchedulerCheck(False, str(exc)[:500])
        return SchedulerCheck(result.returncode == 0, (result.stdout or result.stderr).strip()[:500])

    def register(self, job: BloggerLinkJob) -> None:
        if os.name != "nt":
            raise SchedulerError("Windows Task Scheduler is available only on Windows / Windowsでのみ利用できます")
        try:
            result = subprocess.run(
                build_create_args(job),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SchedulerError(f"Could not register task / タスク登録に失敗しました: {exc}") from exc
        if result.returncode != 0:
            raise SchedulerError((result.stderr or result.stdout).strip() or "schtasks /Create failed")

    def unregister(self, job_id: str) -> None:
        if os.name != "nt":
            raise SchedulerError("Windows Task Scheduler is available only on Windows / Windowsでのみ利用できます")
        try:
            result = subprocess.run(
                ["schtasks", "/Delete", "/TN", task_name(job_id), "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SchedulerError(f"Could not remove task / タスク削除に失敗しました: {exc}") from exc
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            if "cannot find" not in message.lower() and "見つかりません" not in message:
                raise SchedulerError(message or "schtasks /Delete failed")
