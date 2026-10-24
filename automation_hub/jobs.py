from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from .models import BloggerLinkJob, ModelValidationError
from .paths import jobs_path


class JobStoreError(RuntimeError):
    pass


class JobStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or jobs_path()

    def load_all(self) -> list[BloggerLinkJob]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JobStoreError(f"Could not read jobs.json / jobs.jsonを読み込めません: {exc}") from exc
        if not isinstance(raw, list):
            raise JobStoreError("jobs.json root must be a list / jobs.jsonのルートはリストである必要があります")
        jobs: list[BloggerLinkJob] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(raw):
            try:
                job = BloggerLinkJob.from_dict(item)
            except (ModelValidationError, TypeError, ValueError) as exc:
                raise JobStoreError(f"Invalid job at index {index} / {index}番目のジョブが不正です: {exc}") from exc
            if job.id in seen_ids:
                raise JobStoreError(f"Duplicate job id / ジョブIDが重複しています: {job.id}")
            seen_ids.add(job.id)
            jobs.append(job)
        return jobs

    def save_all(self, jobs: Iterable[BloggerLinkJob]) -> None:
        items = list(jobs)
        ids = [job.id for job in items]
        if len(ids) != len(set(ids)):
            raise JobStoreError("Duplicate job id / ジョブIDが重複しています")
        payload = json.dumps([job.to_dict() for job in items], ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="jobs-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_name, self.path)
        except OSError as exc:
            raise JobStoreError(f"Could not save jobs / ジョブを保存できません: {exc}") from exc
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def get(self, job_id: str) -> BloggerLinkJob:
        for job in self.load_all():
            if job.id == job_id:
                return job
        raise KeyError(job_id)

    def upsert(self, job: BloggerLinkJob) -> None:
        jobs = self.load_all()
        for index, existing in enumerate(jobs):
            if existing.id == job.id:
                jobs[index] = job
                break
        else:
            jobs.append(job)
        self.save_all(jobs)

    def delete(self, job_id: str) -> None:
        self.save_all([job for job in self.load_all() if job.id != job_id])
