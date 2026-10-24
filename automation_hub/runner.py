from __future__ import annotations

from .audit import AuditLogger
from .blogger_automation import JobRunResult, run_link_job
from .google_blogger import GoogleBloggerConnector
from .jobs import JobStore
from .models import validate_job_id
from .schedule_approval import ScheduleApprovalStore


def run_saved_job(job_id: str, *, dry_run: bool = False) -> JobRunResult:
    job_id = validate_job_id(job_id)
    job = JobStore().get(job_id)
    if not job.enabled:
        raise RuntimeError(f"Job is disabled / ジョブは無効です: {job_id}")
    if not dry_run and not ScheduleApprovalStore().approved(job):
        raise RuntimeError(
            "Scheduled job is not approved for its current content / "
            "定期実行の内容が未承認か変更されています。GUIで再試運転・再登録してください"
        )
    connector = GoogleBloggerConnector()
    return run_link_job(connector, job, dry_run=dry_run, audit=AuditLogger())
