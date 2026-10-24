"""Small, testable helpers for the first-run UI and safe Blogger execution."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import BloggerLinkJob


def job_revision(job: BloggerLinkJob) -> str:
    """Digest the Blogger write parameters, not scheduling or OAuth secrets.

    A change from daily to weekly does not change the article transformation
    preview; a change to link/text/blog/status always invalidates it.
    """
    operation = job.to_dict().copy()
    operation.pop("schedule", None)
    raw = json.dumps(operation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def needs_save(saved: BloggerLinkJob, edited: BloggerLinkJob) -> bool:
    """Warn before using persisted values that differ from the visible form."""
    return job_revision(saved) != job_revision(edited)


def live_run_ready(
    *,
    job: BloggerLinkJob,
    edited: BloggerLinkJob,
    preview_revision: str | None,
    busy: bool,
) -> tuple[bool, str]:
    """Fail closed on a busy UI, unsaved inputs, or an obsolete/missing preview."""
    if busy:
        return False, "busy"
    if needs_save(job, edited):
        return False, "unsaved"
    if preview_revision != job_revision(job):
        return False, "preview_required"
    return True, "ready"


def home_progress(configured: bool, token_present: bool, job_count: int | None) -> tuple[str, str, str]:
    """Display only confirmed local states; a saved token is NOT API validation."""
    connection = "config_missing" if not configured else ("auth_present" if token_present else "auth_missing")
    jobs = "jobs_error" if job_count is None else ("jobs_ready" if job_count > 0 else "jobs_missing")
    return connection, jobs, "preview_required"
